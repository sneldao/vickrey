"""Evidence ledger HTTP API.

An application event is stored at ingest, then this service independently
GETs the Hornet block and its metadata. solid and content_match are two
different facts: the block's confirmation, and whether the tagged data
still equals the application copy. Tamper changes only the copy.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.atlas import ObservationStore
from app.atlas import connect as connect_observations
from app.context import ContextError
from app.context import context_from_env as open_context
from app.context import DEFAULT_LIMIT as DEFAULT_CONTEXT_LIMIT
from app.db import Database, load_json, normalize_block_id, parse_time_bound
from app.embedded import EmbeddedHornet, embedded_from_env
from app.hornet import DEFAULT_HORNET_URL, HornetClient
from app.tamper import mutate_application_payload
from app.verify import STATUS_VALUES, Status, VerifyResult, verify_record

logger = logging.getLogger("ledger")

TAMPER_NOTE = (
    "DEMO ONLY. payload_json in this database was overwritten. "
    "Hornet was not modified; reverify only GETs the block and metadata."
)


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

    block_id: str = Field(validation_alias=AliasChoices("blockId", "block_id"))
    tag: str
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
    db.save_verification(row["block_id"], result)
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


def create_app(
    *,
    database_path: str | None = None,
    hornet: Any | None = None,
    hornet_url: str | None = None,
    cors_origins: str | None = None,
    observation_store: Any | None = None,
    embedded: Any | None = None,
    context: Any | None = None,
) -> FastAPI:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
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
        version="0.3.0",
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
            "ingest": "/ingest",
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
        }

    @app.post("/context", response_model=ContextResult)
    def context_lookup(body: ContextIn) -> dict:
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

    @app.post("/ingest", response_model=MessageOut)
    def ingest(body: IngestIn, response: Response) -> dict:
        # In embedded mode this service is also the Messages API stand-in, so it
        # writes the block before reading it back. The block still lands in a
        # separate structure from the application copy, which is what the
        # two-source check compares; see app/embedded.py for what this costs.
        if anchoring is not None:
            anchoring.register(
                block_id=body.block_id,
                tag=body.tag,
                message=body.message,
            )
        created = app.state.db.upsert_application(
            block_id=body.block_id,
            tag=body.tag,
            flow_id=extract_flow_id(body.message, body.flow_id),
            payload=body.message,
            hornet_status=body.hornet_status,
        )
        if observations is not None:
            try:
                observations.put(
                    block_id=body.block_id,
                    tag=body.tag,
                    flow_id=extract_flow_id(body.message, body.flow_id),
                    message=body.message,
                )
            except Exception:
                # The ledger is the source of truth. A searchable-mirror miss is
                # logged, not fatal: the anchor and its verification still land.
                logger.exception(
                    "Atlas observation store: mirror failed for %s", body.block_id
                )
        row = verify_stored(app.state.db, app.state.hornet, body.block_id)
        response.status_code = 201 if created else 200
        return message_out(row)

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
    def reverify(block_id: str) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if app.state.db.get(block_id) is None:
            raise HTTPException(status_code=404, detail="message not found")
        row = verify_stored(app.state.db, app.state.hornet, block_id)
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
    def tamper(block_id: str, body: TamperIn | None = _OPTIONAL_TAMPER_BODY) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        app.state.db.update_payload(block_id, mutated)
        logger.warning(
            "DEMO tamper of application payload for %s; Hornet not modified", block_id
        )
        row = verify_stored(app.state.db, app.state.hornet, block_id)
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
    def restore(block_id: str) -> dict:
        try:
            _clean_block_id(block_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        current = app.state.db.get(block_id)
        if current is None:
            raise HTTPException(status_code=404, detail="message not found")
        anchored = load_json(current["ledger_payload_json"])
        if anchored is None:
            raise HTTPException(
                status_code=409,
                detail="no anchored Hornet payload to restore from",
            )
        app.state.db.update_payload(block_id, anchored)
        logger.info(
            "DEMO restore of application payload for %s from anchored block",
            block_id,
        )
        row = verify_stored(app.state.db, app.state.hornet, block_id)
        return message_out(row)

    return app


app = create_app()
