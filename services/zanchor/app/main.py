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

import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db import Receipts
from app.rpc import RpcError, ZcashRpc

logger = logging.getLogger("zanchor")

COMMITMENT_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_ANCHOR_AMOUNT = "0.001"
DEFAULT_FEE = "0.0001"
WORKER_POLL_SECONDS = 2.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def build_rpc() -> ZcashRpc | None:
    url = _env("ZANCHOR_RPC")
    return ZcashRpc(url) if url else None


def build_store() -> Receipts:
    return Receipts(_env("ZANCHOR_DB", "data/zanchor.db"))


class AnchorService:
    """Wallet-facing anchor pipeline plus the receipt book."""

    def __init__(self, rpc: ZcashRpc | None, store: Receipts) -> None:
        self.rpc = rpc
        self.store = store
        self.mode = _env("ZANCHOR_MODE", "B").upper()
        if self.mode not in ("A", "B"):
            raise ValueError(f"ZANCHOR_MODE must be A or B, got {self.mode!r}")
        self.amount = _env("ZANCHOR_ANCHOR_AMOUNT", DEFAULT_ANCHOR_AMOUNT)
        self.fee = _env("ZANCHOR_FEE", DEFAULT_FEE)
        self.anchor_zaddr = _env("ZANCHOR_ANCHOR_ZADDR")
        self.recipient_zaddr = _env("ZANCHOR_RECIPIENT_ZADDR")
        # When set, anchoring refuses to run unless the node's reported
        # network matches (e.g. "regtest" for the demo deployment) — a
        # public service must never spend on a non-demo chain.
        self.expected_network = _env("ZANCHOR_EXPECTED_NETWORK")
        self._lock = threading.Lock()

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

    def anchor(self, commitment: str) -> dict[str, Any]:
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

        # The duplicate check, the in-flight check, the send and the insert
        # all happen under the one lock: a second request must not slip
        # between "not anchored yet" and "operation created" and burn a
        # second note for the same commitment or a second note at all.
        with self._lock:
            existing = self.store.by_commitment(commitment)
            if existing is not None and existing["status"] != "failed":
                raise HTTPException(409, "commitment already anchored")
            if existing is not None:
                # A failed attempt did not anchor anything; allow the retry.
                self.store.delete(existing["receipt_id"])
            # One anchor at a time: the wallet picks its note when the
            # operation is created, and its shielded view lags the chain
            # by a few blocks. A second anchor started before the first
            # one confirms can pick the same note — the node then rejects
            # it as a duplicate nullifier. The field scheduler already
            # spaces anchors by tens of minutes; this is the backstop.
            if self.store.unconfirmed():
                raise HTTPException(503, "anchor in flight; retry once it confirms")
            opid, txid, mode, shielded = self._anchor_tx(commitment)
            status = "broadcast" if txid else "queued"
            receipt = self.store.insert(
                commitment, mode, shielded, opid, txid, status=status
            )
            self._remember_shielded(shielded)
            return _public(receipt)

    def _anchor_tx(self, commitment: str) -> tuple[str | None, str | None, str, bool]:
        """Return (opid, txid, mode, shielded) for one commitment.

        Fail-closed: there is no downgrade path. Mode B anchors the
        commitment in the encrypted memo or not at all; mode A (the
        explicit legacy mode) burns a dedicated note or not at all. A
        refusal is a 503, never a quieter transaction.
        """
        if self.mode == "B":
            try:
                return self._send_shielded(commitment), None, "B", True
            except RpcError:
                raise HTTPException(
                    503, "Shielded memo anchoring unavailable; nothing downgraded"
                ) from None
        try:
            return self._send_shielded(None), None, "A", True
        except RpcError:
            raise HTTPException(
                503, "Shielded beacon unavailable; nothing downgraded"
            ) from None

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

        # A pending receipt is advanced first, under the same lock the
        # worker holds, so verify never reads a half-updated row.
        if row["status"] in ("queued", "broadcast"):
            with self._lock:
                try:
                    self._advance(row)
                except RpcError:
                    pass
                except Exception:
                    raise HTTPException(503, "node unreachable")
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
        if self.rpc is None:
            return
        for pending in self.store.unconfirmed():
            # Same lock verify_receipt holds: a fresh read must never see a
            # half-advanced row, and the row is re-read inside the lock so a
            # receipt settled between listing and advancing is not worked on
            # twice. Only the error type name is logged — the exception body
            # can carry RPC credentials.
            with self._lock:
                try:
                    row = self.store.get(pending["receipt_id"])
                    if row is not None and row["status"] in ("queued", "broadcast"):
                        self._advance(row)
                except Exception as exc:
                    logger.warning(
                        "receipt %s: %s",
                        pending["receipt_id"],
                        type(exc).__name__,
                    )

    def _advance(self, receipt: dict[str, Any]) -> None:
        assert self.rpc is not None
        rid = receipt["receipt_id"]
        if receipt["status"] == "queued":
            if not receipt["opid"]:
                return
            status = self.rpc.operation_status(receipt["opid"])
            state = status.get("status")
            if state == "success":
                result = status.get("result")
                txid = result.get("txid") if isinstance(result, dict) else result
                self.store.set_broadcast(rid, str(txid))
                receipt = self.store.get(rid)
            elif state in ("failed", "error"):
                logger.error("receipt %s op failed: %s", rid, status)
                self.store.set_failed(rid, str(status.get("error", "operation failed")))
                return
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
                )


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
        "shielded": receipt["shielded"],
        "txid": receipt.get("txid"),
        "height": receipt.get("height"),
        "anchored_at": receipt.get("anchored_at"),
    }
    if receipt.get("error"):
        out["error"] = receipt["error"]
    return out


def build_app() -> FastAPI:
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

    def _worker_loop(svc: AnchorService, stop: threading.Event) -> None:
        while not stop.is_set():
            svc.poll_pending()
            stop.wait(WORKER_POLL_SECONDS)

    @app.post("/anchor", status_code=202)
    def anchor(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        commitment = (payload or {}).get("commitment", "")
        if not isinstance(commitment, str) or not COMMITMENT_RE.match(commitment):
            raise HTTPException(400, "body is not a 64-hex commitment")
        # Replay and in-flight checks live inside service.anchor's lock so
        # two racing requests cannot both pass them.
        return service.anchor(commitment)

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
    def disclosure(
        receipt_id: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        purpose = (payload or {}).get("purpose")
        if not isinstance(purpose, str):
            raise HTTPException(400, "purpose is required (1-200 characters)")
        purpose = purpose.strip()
        if not 1 <= len(purpose) <= 200:
            raise HTTPException(400, "purpose is required (1-200 characters)")
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
        }

    return app


app = build_app()
