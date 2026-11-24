"""zanchor — the shielded anchor service.

One observation commitment becomes one deliberately unremarkable Zcash
transaction: constant amount, one dedicated note burned (mode A), or the
commitment carried in the encrypted memo (mode B). The service keeps the
commitment <-> txid <-> height binding as a receipt, served only to the
holder of the receipt id.

The service is the authority on what the transaction actually is:
every receipt and /health carry `mode` (the mechanism it ran) and
`shielded` (whether the transaction that went to the node spent and
received in the shielded pool). Clients derive their labels from
`shielded` and never from `mode` or their own hopes
(docs/ZANCHOR_API.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.db import (
    AnchorInFlight,
    CommitmentConflict,
    IdempotencyConflict,
    QuotaExceeded,
    Receipts,
)
from app.rpc import RpcError, ZcashRpc

logger = logging.getLogger("zanchor")

COMMITMENT_RE = re.compile(r"^[0-9a-f]{64}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

DEFAULT_ANCHOR_AMOUNT = "0.001"
DEFAULT_FEE = "0.0001"
DEFAULT_BODY_LIMIT = 16_384
DEFAULT_ANCHOR_QUOTA = 10
DEFAULT_DISCLOSURE_QUOTA = 30
DEFAULT_QUOTA_WINDOW_SECONDS = 60
DEFAULT_LEASE_SECONDS = 300
WORKER_POLL_SECONDS = 2.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _positive_int_env(name: str, default: int, maximum: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _runtime_environment() -> tuple[str, str | None]:
    env = _env("ZANCHOR_ENV", "demo").lower()
    if env not in ("demo", "production"):
        raise ValueError("ZANCHOR_ENV must be demo or production")
    token = _env("ZANCHOR_API_TOKEN") or None
    if env == "production" and not token:
        raise ValueError("ZANCHOR_API_TOKEN is required in production")
    if token is not None and any(ch.isspace() for ch in token):
        raise ValueError("ZANCHOR_API_TOKEN must not contain whitespace")
    return env, token


def build_rpc() -> ZcashRpc | None:
    url = _env("ZANCHOR_RPC")
    return ZcashRpc(url) if url else None


def build_store() -> Receipts:
    return Receipts(_env("ZANCHOR_DB", "data/zanchor.db"))


class _BodyTooLarge(Exception):
    pass


def _body_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, _BodyTooLarge):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_body_limit_error(item) for item in exc.exceptions)
    return False


class BodyLimitMiddleware:
    """Bound streamed request bodies as well as Content-Length requests."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) > self.max_bytes:
                    await JSONResponse(
                        status_code=413,
                        content={"detail": "request body too large"},
                        headers={"Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
            except ValueError:
                pass
        total = 0

        async def limited_receive() -> dict:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BaseException as exc:
            if not _body_limit_error(exc):
                raise
            await JSONResponse(
                status_code=413,
                content={"detail": "request body too large"},
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)


class AnchorService:
    """Wallet-facing anchor pipeline plus the receipt book."""

    def __init__(self, rpc: ZcashRpc | None, store: Receipts) -> None:
        self.rpc = rpc
        self.store = store
        self.mode = _env("ZANCHOR_MODE", "B").upper()
        if self.mode not in ("A", "B"):
            raise ValueError(f"ZANCHOR_MODE must be A or B, got {self.mode!r}")
        self.env, self.api_token = _runtime_environment()
        self.amount = _env("ZANCHOR_ANCHOR_AMOUNT", DEFAULT_ANCHOR_AMOUNT)
        self.fee = _env("ZANCHOR_FEE", DEFAULT_FEE)
        self.anchor_zaddr = _env("ZANCHOR_ANCHOR_ZADDR")
        self.recipient_zaddr = _env("ZANCHOR_RECIPIENT_ZADDR")
        # When set, anchoring refuses to run unless the node's reported
        # network matches (e.g. "regtest" for the demo deployment) — a
        # public service must never spend on a non-demo chain.
        self.expected_network = _env("ZANCHOR_EXPECTED_NETWORK")
        self.worker_id = f"{os.getpid()}_{uuid.uuid4().hex}"
        self.lease_seconds = _positive_int_env(
            "ZANCHOR_LEASE_SECONDS", DEFAULT_LEASE_SECONDS, 3600
        )
        self.body_limit_bytes = _positive_int_env(
            "ZANCHOR_MAX_BODY_BYTES", DEFAULT_BODY_LIMIT, 1_048_576
        )
        self.quota_window_seconds = _positive_int_env(
            "ZANCHOR_QUOTA_WINDOW_SECONDS", DEFAULT_QUOTA_WINDOW_SECONDS, 86_400
        )
        self.anchor_quota = _positive_int_env(
            "ZANCHOR_ANCHOR_QUOTA", DEFAULT_ANCHOR_QUOTA, 1_000_000
        )
        self.disclosure_quota = _positive_int_env(
            "ZANCHOR_DISCLOSURE_QUOTA", DEFAULT_DISCLOSURE_QUOTA, 1_000_000
        )

    @property
    def auth_required(self) -> bool:
        return self.env == "production"

    # -- capability ------------------------------------------------------

    def node_up(self) -> bool:
        if self.rpc is None:
            return False
        try:
            self.rpc.ping()
            return True
        except Exception:
            return False

    def shielded_pipeline(self) -> bool:
        """Whether the running pipeline currently produces shielded txs.

        Last empirical result wins; before any anchor, it is what the
        node can show us (spendable notes present).
        """
        cached = self.store.kv_get("shielded")
        if cached is not None:
            return cached == "1"
        if self.rpc is None:
            return False
        try:
            return self.rpc.notes_available() > 0
        except Exception:
            return False

    def notes_available(self) -> int:
        if self.rpc is None:
            return 0
        try:
            return self.rpc.notes_available()
        except RpcError:
            # Wallet without shielded support (or no notes) — either way
            # there is nothing to burn.
            return 0

    def _remember_shielded(self, shielded: bool) -> None:
        self.store.kv_set("shielded", "1" if shielded else "0")

    # -- anchoring ---------------------------------------------------------

    def anchor(
        self, commitment: str, idempotency_key: str, request_sha256: str
    ) -> dict[str, Any]:
        try:
            replay = self.store.idempotency_receipt(idempotency_key, request_sha256)
        except IdempotencyConflict:
            raise HTTPException(
                409, "idempotency key reused with different request bytes"
            ) from None
        if replay is not None:
            return _public(replay)
        if not self.node_up():
            raise HTTPException(503, "node unreachable")
        if self.expected_network:
            try:
                raw = self.rpc.network()
            except Exception:
                raise HTTPException(503, "node unreachable")
            if raw != self.expected_network:
                raise HTTPException(
                    503, "anchor service is not on its expected network"
                )

        try:
            receipt, replayed = self.store.reserve_anchor(
                commitment,
                self.mode,
                idempotency_key,
                request_sha256,
                self.worker_id,
                time.time() + self.lease_seconds,
                quota_limit=self.anchor_quota,
                quota_window_seconds=self.quota_window_seconds,
            )
        except IdempotencyConflict:
            raise HTTPException(
                409, "idempotency key reused with different request bytes"
            ) from None
        except CommitmentConflict:
            raise HTTPException(409, "commitment already anchored") from None
        except AnchorInFlight:
            raise HTTPException(
                503, "anchor in flight; retry once it settles"
            ) from None
        except QuotaExceeded:
            raise HTTPException(429, "anchor quota exceeded") from None
        if replayed:
            return _public(receipt)

        # The submitting receipt and lease are durable before this call. If
        # the process dies here, recovery can only reconcile, never resend.
        try:
            opid, mode, shielded = self._anchor_tx(commitment)
            if not isinstance(opid, str) or not opid:
                raise OSError("node returned no operation id")
            receipt = self.store.record_opid(
                receipt["receipt_id"], self.worker_id, opid, mode, shielded
            )
            if receipt is None:
                receipt = self.store.get(receipt["receipt_id"])
            if receipt is None:
                raise RuntimeError("submitted receipt missing")
            self._remember_shielded(shielded)
            return _public(receipt)
        except RpcError as exc:
            if _definite_rpc_failure(exc):
                reason = (
                    "Shielded memo anchoring unavailable; nothing downgraded"
                    if self.mode == "B"
                    else "Shielded beacon unavailable; nothing downgraded"
                )
                receipt = self.store.fail_submission(
                    receipt["receipt_id"], self.worker_id, reason
                )
            else:
                receipt = self.store.mark_submission_reconciling(
                    receipt["receipt_id"],
                    self.worker_id,
                    "submission outcome uncertain; reconciliation required",
                )
            return _public(receipt or self.store.get(receipt["receipt_id"]))
        except HTTPException:
            # Local preflight refusals (for example no spendable note) are
            # definite and retain the same receipt for a keyed retry.
            receipt = self.store.fail_submission(
                receipt["receipt_id"], self.worker_id, "anchor preflight failed"
            )
            return _public(receipt or self.store.get(receipt["receipt_id"]))
        except OSError:
            receipt = self.store.mark_submission_reconciling(
                receipt["receipt_id"],
                self.worker_id,
                "submission outcome uncertain; reconciliation required",
            )
            return _public(receipt or self.store.get(receipt["receipt_id"]))
        except Exception:
            self.store.mark_submission_reconciling(
                receipt["receipt_id"],
                self.worker_id,
                "submission outcome uncertain; reconciliation required",
            )
            raise

    def _anchor_tx(self, commitment: str) -> tuple[str, str, bool]:
        """Submit exactly one shielded operation; never downgrade the mode."""
        if self.mode == "B":
            return self._send_shielded(commitment), "B", True
        return self._send_shielded(None), "A", True

    def _send_shielded(self, commitment: str | None) -> str:
        """One dedicated note burned for one commitment. Returns an opid.

        Raises HTTPException(503) when there is nothing to spend and
        RpcError when the node refuses shielded spends.
        """
        assert self.rpc is not None
        if (
            self.notes_available() == 0
            or not self.anchor_zaddr
            or not self.recipient_zaddr
        ):
            raise HTTPException(503, "no spendable note left")
        memo: str | None = None
        if commitment is not None:
            memo = "00" + commitment  # raw 32-byte memo, kind 0
        return self.rpc.send_shielded(
            self.anchor_zaddr, self.recipient_zaddr, self.amount, self.fee, memo
        )

    # -- verification -------------------------------------------------------

    def _network(self) -> str:
        """The node's own answer, normalised; "unknown" never passes proof."""
        if self.rpc is None:
            return "unknown"
        raw = self.rpc.network()  # raises on transport failure (caller maps)
        return {"main": "main", "test": "testnet", "regtest": "regtest"}.get(
            raw, "unknown"
        )

    def network_name(self) -> str:
        """For /health: a best-effort label that never raises."""
        try:
            return self._network()
        except Exception:
            return "unknown"

    def verify_receipt(self, receipt_id: str) -> dict[str, Any]:
        """Fresh node read for one receipt id (docs/ZANCHOR_API.md).

        transaction_verified is a fact about the chain: the node's own
        transaction record names the receipt's txid, carries at least one
        confirmation, sits at exactly the height the receipt stored when it
        confirmed, and runs on a known network. commitment_verified is
        stronger: it additionally requires the mode-B encrypted memo in the
        transaction's shielded outputs to decode to this commitment, read
        through the service wallet (z_viewtransaction). Nothing about the
        memo's other contents is returned.
        """
        row = self.store.get(receipt_id)
        if row is None:
            raise HTTPException(404, "unknown receipt")
        if self.rpc is None:
            raise HTTPException(503, "no node")

        # A worker lease fences advancement across processes. Verification
        # never submits or resends; it only polls the already-known opid.
        if row["status"] in ("queued", "broadcast", "reconciling"):
            self._poll_one(receipt_id)
            row = self.store.get(receipt_id) or row

        try:
            network = self._network()
        except Exception:
            raise HTTPException(503, "node unreachable")

        tx_verified = False
        memo_verified = False
        height: int | None = None
        confirmations: int | None = None
        txid = row.get("txid")
        if row["status"] != "confirmed" or not txid:
            reason = "receipt_not_confirmed"
        else:
            try:
                tx = self.rpc.transaction(txid)
            except RpcError:
                tx = None
                reason = "transaction_not_on_node"
            except Exception:
                raise HTTPException(503, "node unreachable")
            if tx is not None:
                if tx.get("txid") != txid:
                    # A node answer for a different transaction must never
                    # satisfy this receipt.
                    reason = "txid_mismatch"
                else:
                    raw_height = tx.get("blockheight") or _block_height(
                        self.rpc, tx.get("blockhash")
                    )
                    raw_confs = tx.get("confirmations")
                    # type() not isinstance(): a bool is an int in Python
                    # and must never count as a height or confirmation.
                    height = raw_height if type(raw_height) is int else None
                    confirmations = raw_confs if type(raw_confs) is int else None
                    if confirmations is None or confirmations < 1:
                        reason = "insufficient_confirmations"
                    elif height is None or height < 1:
                        reason = "transaction_unconfirmed"
                    elif height != row.get("height"):
                        # Mempool placement, a reorg, or a wrong stored
                        # height must never pass.
                        reason = "height_mismatch"
                    elif network == "unknown":
                        # The proof only means something on a named chain.
                        reason = "network_unknown"
                    else:
                        tx_verified = True
                        reason = "verifier_record_only"

        if tx_verified:
            if row["mode"] != "B" or not row["shielded"]:
                # The chain shows a transaction; only the receipt book ties
                # it to the commitment. That is verifier-held binding, not
                # a memo proof.
                reason = "verifier_record_only"
            else:
                try:
                    view = self.rpc.view_transaction(txid)
                except RpcError:
                    reason = "memo_unavailable"
                except Exception:
                    raise HTTPException(503, "node unreachable")
                else:
                    if view.get("txid") is not None and view.get("txid") != txid:
                        reason = "txid_mismatch"
                    else:
                        for output in view.get("outputs") or []:
                            if not isinstance(output, dict):
                                continue
                            if memo_matches(output.get("memo"), row["commitment"]):
                                memo_verified = True
                                break
                        reason = (
                            "commitment_in_encrypted_memo"
                            if memo_verified
                            else "memo_mismatch"
                        )

        return {
            "receipt_id": receipt_id,
            "commitment": row["commitment"],
            "txid": row.get("txid"),
            "height": height,
            "confirmations": confirmations,
            "network": network,
            "transaction_verified": tx_verified,
            "commitment_verified": memo_verified,
            "binding": "encrypted_memo" if row["mode"] == "B" else "verifier_record",
            "verification_source": "service_wallet",
            "reason": reason,
        }

    # -- worker ------------------------------------------------------------

    def poll_pending(self) -> None:
        self.store.expire_submitting_leases()
        if self.rpc is None:
            return
        for pending in self.store.unconfirmed():
            self._poll_one(pending["receipt_id"])

    def _poll_one(self, receipt_id: str) -> None:
        if self.rpc is None:
            return
        receipt = self.store.claim_pending(
            receipt_id, self.worker_id, time.time() + self.lease_seconds
        )
        if receipt is None:
            return
        try:
            self._advance(receipt)
        except Exception as exc:
            # Only the error type: exception bodies and receipt ids can carry
            # credentials or bearer capabilities.
            logger.warning("anchor_poll_failed error_type=%s", type(exc).__name__)
        finally:
            self.store.release_lease(receipt_id, self.worker_id)

    def _advance(self, receipt: dict[str, Any]) -> None:
        assert self.rpc is not None
        rid = receipt["receipt_id"]
        worker_id = receipt["worker_id"]
        if receipt["status"] in ("queued", "reconciling"):
            if not receipt["opid"]:
                self.store.mark_pending_reconciling(
                    rid,
                    worker_id,
                    "operation id unavailable; manual reconciliation required",
                )
                return
            try:
                status = self.rpc.operation_status(receipt["opid"])
                state = status.get("status")
                if state == "success":
                    result = status.get("result")
                    txid = result.get("txid") if isinstance(result, dict) else result
                    if not isinstance(txid, str) or not txid:
                        raise ValueError("operation success has no txid")
                    self.store.set_broadcast(rid, txid, worker_id)
                elif state in ("failed", "error"):
                    logger.warning("anchor_operation_failed")
                    self.store.set_failed(rid, "node operation failed", worker_id)
            except Exception:
                self.store.mark_pending_reconciling(
                    rid,
                    worker_id,
                    "operation status unavailable; reconciliation required",
                )
                raise
            return
        if receipt["status"] == "broadcast" and receipt["txid"]:
            tx = self.rpc.transaction(receipt["txid"])
            if tx.get("txid") != receipt["txid"]:
                return
            height = tx.get("blockheight") or _block_height(
                self.rpc, tx.get("blockhash")
            )
            confs = tx.get("confirmations")
            if type(height) is int and height > 0 and type(confs) is int and confs >= 1:
                self.store.set_confirmed(
                    rid,
                    int(height),
                    _iso(
                        tx.get("blocktime")
                        or _block_time(self.rpc, tx.get("blockhash"))
                    ),
                    worker_id,
                )


def _definite_rpc_failure(exc: RpcError) -> bool:
    """A decoded JSON-RPC refusal is definite; a bare HTTP 5xx is not."""
    if exc.code == -32000 and exc.message.startswith("node http"):
        match = re.fullmatch(r"node http (\d+)", exc.message)
        if match:
            return 400 <= int(match.group(1)) < 500
        return False
    return True


def memo_matches(memo: Any, commitment: str) -> bool:
    """Strict wire check for the mode-B memo ("00" + 32-byte commitment).

    The service writes a raw 33-byte memo ("00" + commitment); zcashd pads
    it to the 512-byte memo field with zeroes. Both lengths are accepted —
    the 33-byte form is what the wallet returns on some versions — but the
    payload must match exactly: the first byte is the kind byte, the next
    32 are the commitment, and everything after is padding. A commitment
    appearing anywhere else, or encoded any other way, is not a match.
    """
    if not isinstance(memo, str) or len(memo) not in (66, 1024):
        return False
    try:
        raw = bytes.fromhex(memo)
    except ValueError:
        return False
    # fromhex ignores whitespace — the raw decoded length is the real check.
    if len(raw) not in (33, 512):
        return False
    target = b"\x00" + bytes.fromhex(commitment)
    return raw[:33] == target and all(b == 0 for b in raw[33:])


def _block_time(rpc: ZcashRpc, blockhash: str | None) -> int | None:
    if not blockhash:
        return None
    try:
        return int(rpc.call("getblock", [blockhash])["time"])
    except RpcError:
        return None


def _block_height(rpc: ZcashRpc, blockhash: str | None) -> int | None:
    # 6.x gettransaction carries blockhash but no height field.
    if not blockhash:
        return None
    try:
        return int(rpc.call("getblockheader", [blockhash])["height"])
    except RpcError:
        return None


def _iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _public(receipt: dict[str, Any]) -> dict[str, Any]:
    out = {
        "receipt_id": receipt["receipt_id"],
        "commitment": receipt["commitment"],
        "status": receipt["status"],
        "mode": receipt["mode"],
        # Before an opid exists no transaction has been submitted, so the
        # service must not label the pending attempt transparent or shielded.
        "shielded": (
            receipt["shielded"] if receipt.get("opid") or receipt.get("txid") else None
        ),
        "txid": receipt.get("txid"),
        "height": receipt.get("height"),
        "anchored_at": receipt.get("anchored_at"),
    }
    if receipt.get("error"):
        out["error"] = receipt["error"]
    return out


def build_app() -> FastAPI:
    _runtime_environment()  # fail before opening a store in misconfigured production
    rpc = build_rpc()
    store = build_store()
    service = AnchorService(rpc, store)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal stop
        thread = None
        if rpc is not None:
            thread = threading.Thread(
                target=_worker_loop, args=(service, stop), daemon=True
            )
            thread.start()
        yield
        stop.set()
        if thread is not None:
            thread.join(timeout=5)

    app = FastAPI(title="zanchor", lifespan=lifespan)
    app.state.service = service
    origins = [o for o in _env("ZANCHOR_CORS_ORIGINS", "*").split(",") if o]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"]
    )

    @app.middleware("http")
    async def private_errors(request, call_next):
        try:
            response = await call_next(request)
        except BaseException as exc:
            if _body_limit_error(exc) or not isinstance(exc, Exception):
                raise
            # Unexpected failure: log the type only, answer generically. No
            # traceback, no request detail — both can carry bearer ids.
            logger.error("request_failed error_type=%s", type(exc).__name__)
            response = JSONResponse(
                status_code=500, content={"detail": "internal service error"}
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    def _worker_loop(svc: AnchorService, stop: threading.Event) -> None:
        while not stop.is_set():
            svc.poll_pending()
            stop.wait(WORKER_POLL_SECONDS)

    def _require_write_auth(request: Request) -> None:
        if not service.auth_required:
            return
        scheme, separator, supplied = request.headers.get(
            "authorization", ""
        ).partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(
                supplied.encode("utf-8"), service.api_token.encode("utf-8")
            )
        ):
            raise HTTPException(
                401, "unauthorized", headers={"WWW-Authenticate": "Bearer"}
            )

    def _decode_json_object(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(400, "body must be a JSON object") from None
        if not isinstance(payload, dict):
            raise HTTPException(400, "body must be a JSON object")
        return payload

    async def _json_object(request: Request) -> tuple[dict[str, Any], bytes]:
        raw = await request.body()
        return _decode_json_object(raw), raw

    @app.post("/anchor", status_code=202)
    async def anchor(request: Request) -> dict[str, Any]:
        _require_write_auth(request)
        raw = await request.body()
        idempotency_key = request.headers.get("idempotency-key", "")
        if not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise HTTPException(
                400, "Idempotency-Key must be 8-128 letters, digits, . _ : or -"
            )
        request_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            replay = service.store.idempotency_receipt(idempotency_key, request_sha256)
        except IdempotencyConflict:
            raise HTTPException(
                409, "idempotency key reused with different request bytes"
            ) from None
        if replay is not None:
            return _public(replay)
        payload = _decode_json_object(raw)
        commitment = payload.get("commitment", "")
        if not isinstance(commitment, str) or not COMMITMENT_RE.fullmatch(commitment):
            raise HTTPException(400, "body is not a 64-hex commitment")
        return service.anchor(commitment, idempotency_key, request_sha256)

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str) -> dict[str, Any]:
        row = service.store.get(receipt_id)
        if row is None:
            raise HTTPException(404, "unknown receipt")
        return _public(row)

    @app.get("/receipts/{receipt_id}/verify")
    def verify(receipt_id: str) -> dict[str, Any]:
        # Capability: the receipt id itself. Fresh node read every call —
        # no cached verdict, no private memo or wallet data in the answer.
        return service.verify_receipt(receipt_id)

    @app.post("/receipts/{receipt_id}/disclosure")
    async def disclosure(receipt_id: str, request: Request) -> dict[str, Any]:
        _require_write_auth(request)
        payload, _ = await _json_object(request)
        purpose = payload.get("purpose")
        if not isinstance(purpose, str):
            raise HTTPException(400, "purpose is required (1-200 characters)")
        purpose = purpose.strip()
        if not 1 <= len(purpose) <= 200:
            raise HTTPException(400, "purpose is required (1-200 characters)")
        try:
            service.store.consume_quota(
                "disclosure",
                limit=service.disclosure_quota,
                window_seconds=service.quota_window_seconds,
            )
        except QuotaExceeded:
            raise HTTPException(429, "disclosure quota exceeded") from None
        result = service.verify_receipt(receipt_id)
        if not result["commitment_verified"]:
            raise HTTPException(409, "commitment is not verified; nothing to disclose")
        # The audit line is written only for a disclosure that actually
        # happened; the table is append-only and has no read endpoint.
        service.store.audit_disclosure(receipt_id, purpose)
        row = service.store.get(receipt_id)
        return {
            "schema": "vickrey.receipt-disclosure/1",
            "receipt": _public(row),
            "verification": result,
        }

    @app.get("/chain/tx/{txid}")
    def chain_tx(txid: str) -> dict[str, Any]:
        if service.rpc is None:
            raise HTTPException(503, "no node")
        try:
            tx = service.rpc.transaction(txid)
        except RpcError:
            # Any node-side refusal means "the node does not know this
            # transaction" (unknown id, invalid id, node http crash on a
            # degenerate id). A dead node is a different failure: URLError
            # falls through to 503 below.
            raise HTTPException(404, "node does not know this transaction")
        except Exception as exc:  # noqa: BLE001 - any transport failure
            raise HTTPException(503, f"node unreachable: {type(exc).__name__}")
        return {
            "txid": txid,
            "exists": True,
            "height": tx.get("blockheight")
            or _block_height(service.rpc, tx.get("blockhash")),
            "confirmations": tx.get("confirmations"),
            "block_time": _iso(
                tx.get("blocktime") or _block_time(service.rpc, tx.get("blockhash"))
            ),
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "node": "ok" if service.node_up() else "down",
            "mode": service.mode,
            "shielded": service.shielded_pipeline(),
            "notes_available": service.notes_available(),
            "network": service.network_name(),
            "env": service.env,
            "auth_required": service.auth_required,
            "body_limit_bytes": service.body_limit_bytes,
            "quotas": {
                "window_seconds": service.quota_window_seconds,
                "anchor": service.anchor_quota,
                "disclosure": service.disclosure_quota,
            },
        }

    # Keep the streaming body guard outside the generic error middleware so
    # an oversized chunk becomes 413 rather than a generic 500.
    app.add_middleware(BodyLimitMiddleware, max_bytes=service.body_limit_bytes)
    return app


app = build_app()
