"""FastAPI transport for the standalone Reality Receipts service."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapters import FieldPathDemoRemoteEvidenceAdapter
from app.config import Principal, Settings
from app.db import MutationResult
from app.errors import QuotaExceeded, ServiceError
from app.models import ChallengeIn, EmptyIn, SubmissionIn, VerdictIn
from app.qie import adapter_from_env
from app.service import ReceiptService

logger = logging.getLogger("receipts.http")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
bearer_scheme = HTTPBearer(auto_error=False)
bearer_dependency = Depends(bearer_scheme)


class BodySizeLimitMiddleware:
    """Buffer bounded request bodies so chunked oversize returns 413, not parse 400."""

    def __init__(self, app: Callable[..., Any], max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass
        if scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                break
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay_receive() -> dict:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: dict, receive: Callable, send: Callable) -> None:
        response = JSONResponse(
            status_code=413, content={"detail": "request body exceeds the size limit"}
        )
        await response(scope, receive, send)


class NoStoreMiddleware:
    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        async def with_header(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_header)


def create_app(
    settings: Settings | None = None,
    *,
    remote_adapter: Any = None,
    settlement_adapter: Any = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    if remote_adapter is None and config.demo_field_path:
        remote_adapter = FieldPathDemoRemoteEvidenceAdapter()
    if settlement_adapter is None:
        settlement_adapter = adapter_from_env()
    service = ReceiptService(
        config,
        remote_adapter=remote_adapter,
        settlement_adapter=settlement_adapter,
        clock=clock,
    )
    app = FastAPI(
        title="Reality Receipts",
        version="1.0.0",
        description=(
            "Public-safe claim-to-receipt vertical slice. Remote evidence is contextual; "
            "settlement metadata is explicitly reported by the configured adapter."
        ),
    )
    app.state.settings = config
    app.state.service = service
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=config.max_request_bytes)
    app.add_middleware(NoStoreMiddleware)

    def require_roles(*roles: str) -> Callable:
        def dependency(
            request: Request,
            credentials: HTTPAuthorizationCredentials | None = bearer_dependency,
        ) -> Principal:
            if credentials is None or credentials.scheme.lower() != "bearer":
                raise ServiceError("bearer token required", status_code=401)
            supplied = credentials.credentials
            matched: Principal | None = None
            for token, principal in config.tokens.items():
                if hmac.compare_digest(token, supplied):
                    matched = principal
                    break
            if matched is None:
                raise ServiceError("invalid bearer token", status_code=401)
            if matched.role not in roles:
                raise ServiceError(
                    "token role is not allowed for this operation", status_code=403
                )
            return matched

        return dependency

    claimant = require_roles("claimant")
    observer = require_roles("observer")
    verifier = require_roles("verifier")
    settlement = require_roles("settlement")
    submission_reader = require_roles("claimant", "observer", "verifier", "settlement")

    def idempotency_key(request: Request) -> str:
        value = request.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_RE.fullmatch(value):
            raise ServiceError(
                "Idempotency-Key must be 8-128 letters, digits, dot, underscore, colon or hyphen",
                status_code=400,
            )
        return value

    async def raw_body_hash(request: Request) -> str:
        # Exact request bytes are part of the idempotency contract. FastAPI has
        # already cached the bounded body while validating the request model.
        return hashlib.sha256(await request.body()).hexdigest()

    claimant_dependency = Depends(claimant)
    observer_dependency = Depends(observer)
    verifier_dependency = Depends(verifier)
    settlement_dependency = Depends(settlement)
    submission_reader_dependency = Depends(submission_reader)
    idempotency_dependency = Depends(idempotency_key)
    raw_hash_dependency = Depends(raw_body_hash)
    optional_empty_body = Body(default=None)

    def result_response(result: MutationResult) -> JSONResponse:
        return JSONResponse(
            status_code=result.status_code,
            content=result.data,
            headers={
                "Idempotency-Replayed": "true" if result.replayed else "false",
                "Cache-Control": "no-store",
            },
        )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, QuotaExceeded):
            headers["Retry-After"] = str(exc.retry_after)
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Never log request bodies, bearer tokens or observation metadata.
        logger.error("request_failed error_type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal service error", "code": "internal_error"},
        )

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": config.mode,
            "remote_evidence_provider": service.remote_adapter.provider,
            "settlement_adapter": service.settlement_adapter.name,
            "settlement_network": getattr(
                service.settlement_adapter, "network", "simulated_testnet"
            ),
            "real_funds": bool(
                getattr(service.settlement_adapter, "real_funds", False)
            ),
            "settlement_amount_unit": getattr(
                service.settlement_adapter, "amount_unit", "simulated_credit"
            ),
        }

    @app.post("/v1/challenges", status_code=201)
    def create_challenge(
        payload: ChallengeIn,
        principal: Principal = claimant_dependency,
        key: str = idempotency_dependency,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        request_hash = service.request_hash(
            "create_challenge", "/v1/challenges", {"raw_body_sha256": raw_hash}
        )
        return result_response(
            service.create_challenge(
                principal, payload, idempotency_key=key, request_hash=request_hash
            )
        )

    @app.get("/v1/challenges/{challenge_id}")
    def get_challenge(challenge_id: str) -> dict[str, Any]:
        return service.get_challenge(challenge_id)

    @app.post("/v1/challenges/{challenge_id}/remote-evidence", status_code=201)
    def run_remote_evidence(
        challenge_id: str,
        principal: Principal = claimant_dependency,
        key: str = idempotency_dependency,
        payload: EmptyIn | None = optional_empty_body,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        return result_response(
            service.run_remote_evidence(
                principal,
                challenge_id,
                idempotency_key=key,
                request_hash=service.request_hash(
                    "remote_evidence",
                    f"/v1/challenges/{challenge_id}/remote-evidence",
                    {"raw_body_sha256": raw_hash},
                ),
            )
        )

    @app.post("/v1/challenges/{challenge_id}/field-task", status_code=201)
    def create_field_task(
        challenge_id: str,
        principal: Principal = claimant_dependency,
        key: str = idempotency_dependency,
        payload: EmptyIn | None = optional_empty_body,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        return result_response(
            service.create_field_task(
                principal,
                challenge_id,
                idempotency_key=key,
                request_hash=service.request_hash(
                    "field_task",
                    f"/v1/challenges/{challenge_id}/field-task",
                    {"raw_body_sha256": raw_hash},
                ),
            )
        )

    @app.post("/v1/challenges/{challenge_id}/submissions", status_code=201)
    def submit_evidence(
        challenge_id: str,
        payload: SubmissionIn,
        principal: Principal = observer_dependency,
        key: str = idempotency_dependency,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        return result_response(
            service.submit_evidence(
                principal,
                challenge_id,
                payload,
                idempotency_key=key,
                request_hash=service.request_hash(
                    "submit_evidence",
                    f"/v1/challenges/{challenge_id}/submissions",
                    {"raw_body_sha256": raw_hash},
                ),
            )
        )

    @app.get("/v1/submissions/{submission_id}")
    def get_submission(
        submission_id: str,
        principal: Principal = submission_reader_dependency,
    ) -> dict[str, Any]:
        return service.get_submission(principal, submission_id)

    @app.post("/v1/submissions/{submission_id}/verdicts", status_code=201)
    def record_verdict(
        submission_id: str,
        payload: VerdictIn,
        principal: Principal = verifier_dependency,
        key: str = idempotency_dependency,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        if str(payload.submission_id) != submission_id:
            raise ServiceError(
                "path and body submission_id do not match", status_code=422
            )
        return result_response(
            service.record_verdict(
                principal,
                payload,
                idempotency_key=key,
                request_hash=service.request_hash(
                    "resolve",
                    f"/v1/submissions/{submission_id}/verdicts",
                    {"raw_body_sha256": raw_hash},
                ),
            )
        )

    @app.post("/v1/verdicts/{verdict_id}/settlement", status_code=201)
    def settle(
        verdict_id: str,
        principal: Principal = settlement_dependency,
        key: str = idempotency_dependency,
        payload: EmptyIn | None = optional_empty_body,
        raw_hash: str = raw_hash_dependency,
    ) -> JSONResponse:
        return result_response(
            service.settle(
                principal,
                verdict_id,
                idempotency_key=key,
                request_hash=service.request_hash(
                    "settlement",
                    f"/v1/verdicts/{verdict_id}/settlement",
                    {"raw_body_sha256": raw_hash},
                ),
            )
        )

    @app.get("/v1/receipts/{challenge_id}")
    def public_receipt(challenge_id: str) -> dict[str, Any]:
        return service.public_receipt(challenge_id)

    return app
