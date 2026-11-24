"""Evidence ledger HTTP API.

An application event is stored at ingest, then this service independently
GETs the Hornet block and its metadata. solid and content_match are two
different facts: the block's confirmation, and whether the tagged data
still equals the application copy. Tamper changes only the copy.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.atlas import ObservationStore
from app.atlas import connect as connect_observations
from app.context import ContextError
from app.context import context_from_env as open_context
from app.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from app.db import (
    ApplicationConflict,
    Database,
    IdempotencyConflict,
    load_json,
    normalize_block_id,
    parse_time_bound,
)
from app.embedded import EmbeddedHornet, embedded_from_env
from app.hornet import DEFAULT_HORNET_URL, HornetClient
from app.tamper import mutate_application_payload
from app.verify import STATUS_VALUES, Status, VerifyResult, verify_record

logger = logging.getLogger("ledger")

TAMPER_NOTE = (
    "DEMO ONLY. The active application copy was overwritten; the immutable "
    "submission was not. Hornet was not modified."
)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class VerificationConflict(Exception):
    pass


class ContextIn(BaseModel):
    """What the field client knows about a sighting when it asks for context.

    Deliberately carries no coordinate: ``place`` is an observer-supplied label
    already coarse enough to publish, and the anchoring rule is not relaxed
    because a search engine wants a location.
    """

    species: str = Field(min_length=1, max_length=160)
    # Accepted but not sent to Tavily: measured against the live API, including
    # the kind diluted the query and pulled in irrelevant pages. See
    # app/context.build_query.
    kind: str | None = Field(default=None, max_length=40)
    place: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=DEFAULT_CONTEXT_LIMIT, ge=1, le=20)


class ContextResult(BaseModel):
    provider: str
    query: str
    answer: str | None = None
    credits: int | None = None
    elapsed: float | None = None
    error: str | None = None
    results: list[dict] = Field(default_factory=list)


class IngestIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    block_id: str = Field(
        min_length=1,
        max_length=256,
        validation_alias=AliasChoices("blockId", "block_id"),
    )
    tag: str = Field(min_length=1, max_length=256)
    message: Any
    hornet_status: int | None = Field(
        default=None,
        validation_alias=AliasChoices("hornetStatus", "hornet_status"),
    )
    flow_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("flowId", "flow_id"),
    )

    @field_validator("block_id")
    @classmethod
    def block_id_present(cls, value: str) -> str:
        return _clean_block_id(value)


class TamperIn(BaseModel):
    payload: Any = None
    message: Any = None
    temperature: float | None = None


class MessageOut(BaseModel):
    block_id: str
    tag: str
    flow_id: str | None
    payload_json: Any
    submission_payload_json: Any
    version: int
    inserted_at: str
    solid: bool | None
    content_match: bool | None
    milestone_index: int | None
    raw_block: dict | None
    ledger_payload_json: Any
    ledger_tag: str | None
    status: str
    verified_at: str | None
    hornet_status: int | None = None
    detail: str | None = None
    updated_at: str | None = None


class MessageList(BaseModel):
    count: int
    total: int
    messages: list[MessageOut]


class ObservationHit(BaseModel):
    block_id: str
    tag: str
    flow_id: str | None = None
    label: str | None = None
    kind: str | None = None
    species: str | None = None
    observed_at: str | None = None
    model_id: str | None = None
    commitment: str | None = None
    location: dict | None = None
    score: float | None = None


class ObservationList(BaseModel):
    count: int
    store: str
    observations: list[ObservationHit]


# FastAPI treats a Body() default as the request body. Kept at module scope so
# the route signature does not call Body() inline.
_OPTIONAL_TAMPER_BODY = Body(default=None)


class TamperOut(BaseModel):
    demo_only: bool = True
    note: str
    previous_payload_json: Any
    message: MessageOut


def _clean_block_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError("block_id must be a non-empty id without spaces")
    if not normalize_block_id(value):
        raise ValueError("block_id must be a non-empty id without spaces")
    return value.strip()


def extract_flow_id(message: Any, explicit: str | None) -> str | None:
    if explicit is not None and str(explicit).strip() != "":
        return str(explicit).strip()
    if isinstance(message, dict):
        for key in ("flow_id", "flowId", "flowID"):
            value = message.get(key)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    return None


def message_out(row: dict) -> dict:
    return {
        "block_id": row["block_id"],
        "tag": row["tag"],
        "flow_id": row["flow_id"],
        "payload_json": load_json(row["payload_json"]),
        "submission_payload_json": load_json(row["submission_payload_json"]),
        "version": row["version"],
        "inserted_at": row["inserted_at"],
        "solid": None if row["solid"] is None else bool(row["solid"]),
        "content_match": None
        if row["content_match"] is None
        else bool(row["content_match"]),
        "milestone_index": row["milestone_index"],
        "raw_block": load_json(row["raw_block"]),
        "ledger_payload_json": load_json(row["ledger_payload_json"]),
        "ledger_tag": row["ledger_tag"],
        "status": row["status"],
        "verified_at": row["verified_at"],
        "hornet_status": row["hornet_status"],
        "detail": row["detail"],
        "updated_at": row["updated_at"],
    }


def _pending_error(detail: str) -> VerifyResult:
    return VerifyResult(
        solid=None,
        content_match=None,
        milestone_index=None,
        raw_block=None,
        ledger_payload=None,
        ledger_tag=None,
        status=Status.PENDING.value,
        detail=detail,
    )


def verify_stored(db: Database, hornet: Any, block_id: str) -> dict:
    row = db.get(block_id)
    if row is None:
        raise KeyError(block_id)
    payload = load_json(row["payload_json"])
    try:
        fetch = hornet.fetch(row["block_id"])
        result = verify_record(row["tag"], payload, fetch)
    except Exception as exc:
        logger.exception("verification failed for %s", block_id)
        result = _pending_error(f"verification error: {exc}")
    applied = db.save_verification(
        row["block_id"],
        result,
        expected_version=row["version"],
        checked_payload_json=row["payload_json"],
        checked_tag=row["tag"],
    )
    if not applied:
        raise VerificationConflict(block_id)
    updated = db.get(block_id)
    if updated is None:
        raise KeyError(block_id)
    logger.info(
        "verified %s status=%s solid=%s content_match=%s",
        updated["block_id"],
        updated["status"],
        updated["solid"],
        updated["content_match"],
    )
    return updated


def _cors_origins(raw: str | None) -> list[str]:
    """Browser origins allowed to call the ledger.

    The explorer is a separate origin (port 8090 by default). Verify and
    tamper bodies are unchanged; this only adds the CORS headers those
    browser calls need. ``*`` is the pitch default. Set LEDGER_CORS_ORIGINS
    to a comma-separated list, for example http://localhost:8090.
    """
    text = "*" if raw is None or not raw.strip() else raw.strip()
    if text == "*":
        return ["*"]
    origins = [part.strip() for part in text.split(",") if part.strip()]
    return origins or ["*"]


def _open_observation_store(explicit: Any | None) -> ObservationStore | None:
    """Resolve the Atlas observation store, if one is configured.

    An injected store always wins (tests pass a fake). Otherwise MONGODB_URI
    turns it on. A missing driver or an unreachable cluster must not stop the
    evidence ledger from serving: the ledger is the source of truth, the store
    is a searchable mirror. Failure is logged and the store stays off.
    """
    if explicit is not None:
        return explicit
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        store = connect_observations(uri)
    except Exception:
        logger.exception("Atlas observation store disabled: connect failed")
        return None
    try:
        store.ensure_indexes()
    except Exception:
        logger.exception("Atlas observation store: index setup failed")
    logger.info(
        "Atlas observation store enabled (db=%s)",
        os.environ.get("MONGODB_DB", "vickrey"),
    )
    return store


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def create_app(
    *,
    database_path: str | None = None,
    hornet: Any | None = None,
    hornet_url: str | None = None,
    cors_origins: str | None = None,
    observation_store: Any | None = None,
    embedded: Any | None = None,
    context: Any | None = None,
    mode: str | None = None,
    api_token: str | None = None,
    demo_mutations: bool | None = None,
    max_body_bytes: int | None = None,
    ingest_rate_limit: int | None = None,
    context_rate_limit: int | None = None,
    rate_window_seconds: int | None = None,
) -> FastAPI:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    resolved_mode = (mode or os.environ.get("LEDGER_MODE", "demo")).strip().lower()
    if resolved_mode not in {"demo", "production"}:
        raise ValueError("LEDGER_MODE must be demo or production")
    resolved_token = (
        api_token if api_token is not None else os.environ.get("LEDGER_API_TOKEN")
    )
    resolved_token = resolved_token.strip() if resolved_token else ""
    if resolved_mode == "production" and not resolved_token:
        raise ValueError("LEDGER_API_TOKEN is required in production mode")
    resolved_demo = (
        _env_flag("LEDGER_DEMO_MUTATIONS") if demo_mutations is None else demo_mutations
    )
    if resolved_mode == "production" and resolved_demo:
        raise ValueError("demo mutations cannot be enabled in production mode")
    body_limit = (
        _env_positive_int("LEDGER_MAX_BODY_BYTES", 1_048_576)
        if max_body_bytes is None
        else max_body_bytes
    )
    ingest_limit = (
        _env_positive_int("LEDGER_INGEST_RATE_LIMIT", 60)
        if ingest_rate_limit is None
        else ingest_rate_limit
    )
    context_limit = (
        _env_positive_int("LEDGER_CONTEXT_RATE_LIMIT", 10)
        if context_rate_limit is None
        else context_rate_limit
    )
    rate_window = (
        _env_positive_int("LEDGER_RATE_WINDOW_SECONDS", 60)
        if rate_window_seconds is None
        else rate_window_seconds
    )
    if min(body_limit, ingest_limit, context_limit, rate_window) < 1:
        raise ValueError("request limits must be positive")
    resolved_url = hornet_url or os.environ.get("HORNET_URL", DEFAULT_HORNET_URL)
    timeout = float(os.environ.get("HORNET_TIMEOUT", "5"))
    db_path = database_path or os.environ.get(
        "DATABASE_PATH",
        os.path.join(os.path.dirname(__file__), "..", "data", "ledger.db"),
    )
    database = Database(db_path)

    # An injected reader always wins (tests pass a fake). Otherwise HORNET_EMBEDDED
    # selects the in-process block store, and only failing that do we build the
    # HTTP client -- so a deployed ledger needs one process, not two.
    #
    # ``embedded`` accepts None (read the environment), a bool, or a ready
    # EmbeddedHornet to share with the caller.
    if embedded is None:
        store = embedded_from_env()
    elif isinstance(embedded, EmbeddedHornet):
        store = embedded
    elif embedded:
        store = EmbeddedHornet()
    else:
        store = None

    anchoring = store if hornet is None else None
    reader = (
        hornet
        if hornet is not None
        else (store or HornetClient(resolved_url, timeout=timeout))
    )
    if anchoring is not None:
        resolved_url = anchoring.url
    observations = _open_observation_store(observation_store)
    # Web context is optional: no key means the route reports it is off, and
    # nothing else in the ledger changes.
    web = open_context() if context is None else context

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "evidence ledger db=%s hornet=%s embedded=%s",
            database.path,
            resolved_url,
            anchoring is not None,
        )
        yield
        reader.close()
        if web is not None:
            web.close()

    app = FastAPI(
        title="Vickrey evidence ledger",
        summary=(
            "Application evidence compared with an independently read tagged-data "
            "block. With HORNET_EMBEDDED=1 the block store is in-process and the "
            "check compares two stores rather than two processes."
        ),
        version="0.4.0",
        lifespan=lifespan,
    )
    app.state.db = database
    app.state.hornet = reader
    app.state.hornet_url = resolved_url
    app.state.anchoring = anchoring
    app.state.observations = observations
    origin_setting = (
        os.environ.get("LEDGER_CORS_ORIGINS", "*")
        if cors_origins is None
        else cors_origins
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(origin_setting),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.mode = resolved_mode
    app.state.api_token_required = resolved_mode == "production"
    app.state.demo_mutations = resolved_demo

    async def read_body_limited(request: Request) -> bytes:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > body_limit:
                raise HTTPException(status_code=413, detail="request body is too large")
        raw = bytes(body)
        # BaseHTTPMiddleware otherwise forwards an empty body after stream()
        # consumption. Its cached-request wrapper replays this exact body.
        request._body = raw
        return raw

    @app.middleware("http")
    async def body_size_limit(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return JSONResponse(
                    status_code=400, content={"detail": "invalid content-length"}
                )
            if length < 0:
                return JSONResponse(
                    status_code=400, content={"detail": "invalid content-length"}
                )
            if length > body_limit:
                return JSONResponse(
                    status_code=413, content={"detail": "request body is too large"}
                )
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                await read_body_limited(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code, content={"detail": exc.detail}
                )
        return await call_next(request)

    def _authorize(request: Request, operation: str, limit: int) -> None:
        header = request.headers.get("authorization")
        if resolved_token:
            scheme, separator, credential = (header or "").partition(" ")
            if (
                not separator
                or scheme.lower() != "bearer"
                or not secrets.compare_digest(credential, resolved_token)
            ):
                raise HTTPException(
                    status_code=401,
                    detail="valid bearer token required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            subject = "token:" + hashlib.sha256(resolved_token.encode()).hexdigest()
        elif header:
            raise HTTPException(
                status_code=401,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            host = request.client.host if request.client else "unknown"
            subject = "anonymous:" + host
        allowed, retry_after = database.consume_request_limit(
            subject=subject,
            operation=operation,
            limit=limit,
            window_seconds=rate_window,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="request limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

    def _require_demo() -> None:
        if not resolved_demo:
            raise HTTPException(status_code=403, detail="demo mutations are disabled")

    def _anchoring_mode() -> str:
        """Name the current anchoring mode, and say what it costs.

        A service that overstates its own guarantees is worse than no service,
        so the honest mode string is part of the public surface rather than a
        log line. In embedded mode the ledger writes the block before reading it
        back, which is a weaker claim than "independently reads" and has to be
        visible to anyone reading the API.
        """
        if anchoring is not None:
            return "embedded"
        return "messages-api"

    @app.get("/")
    def root() -> dict:
        return {
            "service": "vickrey-evidence-ledger",
            "role": (
                "Store the application event, read the tagged-data block back, "
                "and compare them. Not a tangle explorer."
            ),
            # Stated plainly, because in embedded mode the ledger both writes and
            # reads the block, so it is not an independent source.
            "anchoring": _anchoring_mode(),
            "guarantee": (
                {
                    "independent_source": False,
                    "note": (
                        "The block store is in this process. The application copy "
                        "is still a separate store, so an edited copy still yields "
                        "PAYLOAD_MISMATCH -- but the block is not held by a "
                        "separate process. Run with HORNET_URL to get that."
                    ),
                }
                if anchoring is not None
                else {
                    "independent_source": True,
                    "note": (
                        "This service only ever reads the block; another process "
                        "submitted it."
                    ),
                }
            ),
            "health": "/health",
            "docs": "/docs",
            "mode": resolved_mode,
            "ingest": "/v2/ingest",
            "demo_ingest": "/ingest" if resolved_mode == "demo" else None,
            "demo_mutations": resolved_demo,
            "messages": "/messages",
            "context": "/context" if web is not None else None,
            "observations": {
                "recent": "/observations/recent",
                "similar": "/observations/similar",
            }
            if observations
            else None,
        }

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "service": "ledger",
            "hornet_url": app.state.hornet_url,
            "anchoring": _anchoring_mode(),
            "independent_source": anchoring is None,
            "context": web is not None,
            "blocks_registered": (
                anchoring.registered if anchoring is not None else None
            ),
            "observations": observations is not None,
            "mode": resolved_mode,
            "api_token_required": resolved_mode == "production",
            "demo_mutations": resolved_demo,
        }

    @app.post("/context", response_model=ContextResult)
    def context_lookup(body: ContextIn, request: Request) -> dict:
        """Recent public reports of a species, from Tavily.

        Deliberately separate from the record: nothing here is sealed, anchored
        or stored. It is public knowledge about the species, and it must never
        become part of a commitment the observer is expected to reproduce.
        """
        if web is None:
            raise HTTPException(
                status_code=503,
                detail="no web context configured; set TAVILY_API_KEY",
            )
        _authorize(request, "context", context_limit)
        try:
            return web.search(
                species=body.species,
                place=body.place,
                limit=body.limit,
            )
        except ContextError as exc:
            # 200 with an error field: the page should show why the lookup
            # failed, not fall over because a third party is down.
            return {
                "provider": "tavily",
                "query": body.species,
                "error": str(exc),
                "results": [],
            }

    def _ingest_body(
        body: IngestIn,
        response: Response,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> dict:
        try:
            submission = app.state.db.submit_application(
                block_id=body.block_id,
                tag=body.tag,
                flow_id=extract_flow_id(body.message, body.flow_id),
                payload=body.message,
                hornet_status=body.hornet_status,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except (ApplicationConflict, IdempotencyConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if submission.replayed and submission.row["status"] != "PENDING":
            response.status_code = 200
            return message_out(submission.row)

        # Embedded mode writes the block before reading it back. Registration is
        # idempotent, so a retry can finish an interrupted first attempt.
        if anchoring is not None:
            anchoring.register(
                block_id=body.block_id,
                tag=body.tag,
                message=body.message,
            )
        if observations is not None and submission.created:
            try:
                observations.put(
                    block_id=body.block_id,
                    tag=body.tag,
                    flow_id=extract_flow_id(body.message, body.flow_id),
                    message=body.message,
                )
            except Exception:
                logger.exception(
                    "Atlas observation store: mirror failed for %s", body.block_id
                )
        try:
            row = verify_stored(app.state.db, app.state.hornet, body.block_id)
        except VerificationConflict:
            row = app.state.db.get(body.block_id)
            if row is None:
                raise HTTPException(status_code=404, detail="message not found")
        response.status_code = 201 if submission.created else 200
        return message_out(row)

    @app.post(
        "/ingest",
        response_model=MessageOut,
        summary="DEMO ONLY: immutable submission without an idempotency key",
    )
    def ingest(body: IngestIn, request: Request, response: Response) -> dict:
        if resolved_mode == "production":
            raise HTTPException(
                status_code=403, detail="use authenticated /v2/ingest in production"
            )
        _authorize(request, "ingest", ingest_limit)
        return _ingest_body(body, response)

    @app.post("/v2/ingest", response_model=MessageOut)
    async def ingest_v2(body: IngestIn, request: Request, response: Response) -> dict:
        _authorize(request, "ingest", ingest_limit)
        raw = await read_body_limited(request)
        key = (request.headers.get("idempotency-key") or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key must be 8-128 letters, digits, . _ : or -",
            )
        return _ingest_body(
            body,
            response,
            idempotency_key=key,
            request_hash=hashlib.sha256(raw).hexdigest(),
        )

    @app.get("/observations/similar", response_model=ObservationList)
    def observations_similar(
        q: str,
        limit: int = Query(default=5, ge=1, le=50),
        tag: str | None = None,
        flowId: str | None = None,
        flow_id: str | None = None,
    ) -> dict:
        """Vector search over observation anchors, nearest first.

        Returns anchors only: label, coarse location, commitment. Never the raw
        observation. 503 when no Atlas store is configured.
        """
        if observations is None:
            raise HTTPException(
                status_code=503,
                detail="no observation store configured; set MONGODB_URI",
            )
        chosen_flow = flowId if flowId is not None else flow_id
        hits = observations.similar_to_text(
            q, limit=limit, tag=tag, flow_id=chosen_flow
        )
        return {"count": len(hits), "store": "mongodb-atlas", "observations": hits}

    @app.get("/observations/recent", response_model=ObservationList)
    def observations_recent(
        limit: int = Query(default=20, ge=1, le=200),
        tag: str | None = None,
        flowId: str | None = None,
        flow_id: str | None = None,
    ) -> dict:
        if observations is None:
            raise HTTPException(
                status_code=503,
                detail="no observation store configured; set MONGODB_URI",
            )
        chosen_flow = flowId if flowId is not None else flow_id
        hits = observations.recent(limit=limit, tag=tag, flow_id=chosen_flow)
        return {"count": len(hits), "store": "mongodb-atlas", "observations": hits}

    @app.get("/messages", response_model=MessageList)
    def list_messages(
        blockId: str | None = None,
        block_id: str | None = None,
        tag: str | None = None,
        flowId: str | None = None,
        flow_id: str | None = None,
        status: str | None = None,
        from_ts: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        chosen_block = blockId or block_id
        chosen_flow = flowId if flowId is not None else flow_id
        if status is not None:
            status = status.strip().upper()
            if status not in STATUS_VALUES:
                allowed = ", ".join(STATUS_VALUES)
                raise HTTPException(
                    status_code=400, detail=f"status must be one of {allowed}"
                )
        try:
            from_bound = (
                None if from_ts is None else parse_time_bound(from_ts, end=False)
            )
            to_bound = None if to is None else parse_time_bound(to, end=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="from and to must be ISO-8601 dates or datetimes",
            ) from exc
        rows, total = app.state.db.list_messages(
            block_id=chosen_block,
            tag=tag,
            flow_id=chosen_flow,
            status=status,
            from_ts=from_bound,
            to_ts=to_bound,
            limit=limit,
            offset=offset,
        )
        messages = [message_out(row) for row in rows]
        return {"count": len(messages), "total": total, "messages": messages}

    @app.get("/messages/{block_id}", response_model=MessageOut)
    def get_message(block_id: str) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = app.state.db.get(block_id)
        if row is None:
            raise HTTPException(status_code=404, detail="message not found")
        return message_out(row)

    @app.post("/messages/{block_id}/reverify", response_model=MessageOut)
    def reverify(block_id: str, request: Request) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _authorize(request, "reverify", ingest_limit)
        if app.state.db.get(block_id) is None:
            raise HTTPException(status_code=404, detail="message not found")
        try:
            row = verify_stored(app.state.db, app.state.hornet, block_id)
        except VerificationConflict as exc:
            raise HTTPException(
                status_code=409, detail="message changed during verification; retry"
            ) from exc
        return message_out(row)

    @app.post(
        "/messages/{block_id}/tamper",
        response_model=TamperOut,
        summary="DEMO ONLY: overwrite the application payload, then reverify",
        description=(
            "Changes payload_json (the application copy) and optionally the "
            "temperature field. Does not submit anything to Hornet. A following "
            "reverify compares the mutated copy with the original tagged data, "
            "so content_match becomes false and status becomes PAYLOAD_MISMATCH "
            "while the block is still readable."
        ),
    )
    def tamper(
        block_id: str, request: Request, body: TamperIn | None = _OPTIONAL_TAMPER_BODY
    ) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _require_demo()
        _authorize(request, "demo-mutation", ingest_limit)
        current = app.state.db.get(block_id)
        if current is None:
            raise HTTPException(status_code=404, detail="message not found")
        if body is None:
            body = TamperIn()
        previous = load_json(current["payload_json"])
        replacement_set = (
            "payload" in body.model_fields_set or "message" in body.model_fields_set
        )
        if "payload" in body.model_fields_set:
            replacement = body.payload
        elif "message" in body.model_fields_set:
            replacement = body.message
        else:
            replacement = None
        try:
            mutated = mutate_application_payload(
                previous,
                replacement=replacement,
                replacement_set=replacement_set,
                temperature=body.temperature,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        changed = app.state.db.update_payload(
            block_id, mutated, expected_version=current["version"]
        )
        if not changed:
            raise HTTPException(
                status_code=409, detail="message changed before tamper; retry"
            )
        logger.warning(
            "DEMO tamper of application payload for %s; Hornet not modified", block_id
        )
        try:
            row = verify_stored(app.state.db, app.state.hornet, block_id)
        except VerificationConflict as exc:
            raise HTTPException(
                status_code=409, detail="message changed during verification; retry"
            ) from exc
        return {
            "demo_only": True,
            "note": f"{TAMPER_NOTE} Status after reverify: {row['status']}.",
            "previous_payload_json": previous,
            "message": message_out(row),
        }

    @app.post(
        "/messages/{block_id}/restore",
        response_model=MessageOut,
        summary="DEMO ONLY: restore the application payload from the anchored block",
        description=(
            "Copies the stored Hornet tagged data back into payload_json "
            "byte-identically, then reverifies. This is the recovery half of "
            "the tamper demo: the block never changed, so putting its payload "
            "back restores VERIFIED."
        ),
    )
    def restore(block_id: str, request: Request) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _require_demo()
        _authorize(request, "demo-mutation", ingest_limit)
        current = app.state.db.get(block_id)
        if current is None:
            raise HTTPException(status_code=404, detail="message not found")
        anchored = load_json(current["ledger_payload_json"])
        if anchored is None:
            raise HTTPException(
                status_code=409,
                detail="no anchored Hornet payload to restore from",
            )
        changed = app.state.db.update_payload(
            block_id, anchored, expected_version=current["version"]
        )
        if not changed:
            raise HTTPException(
                status_code=409, detail="message changed before restore; retry"
            )
        logger.info(
            "DEMO restore of application payload for %s from anchored block",
            block_id,
        )
        try:
            row = verify_stored(app.state.db, app.state.hornet, block_id)
        except VerificationConflict as exc:
            raise HTTPException(
                status_code=409, detail="message changed during verification; retry"
            ) from exc
        return message_out(row)

    return app


app = create_app()
