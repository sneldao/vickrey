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
        self.mode = _env("ZANCHOR_MODE", "A").upper()
        if self.mode not in ("A", "B"):
            self.mode = "A"
        self.amount = _env("ZANCHOR_ANCHOR_AMOUNT", DEFAULT_ANCHOR_AMOUNT)
        self.fee = _env("ZANCHOR_FEE", DEFAULT_FEE)
        self.anchor_zaddr = _env("ZANCHOR_ANCHOR_ZADDR")
        self.recipient_zaddr = _env("ZANCHOR_RECIPIENT_ZADDR")
        self.recipient_taddr = _env("ZANCHOR_RECIPIENT_TADDR")
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

        with self._lock:
            opid, txid, mode, shielded = self._anchor_tx(commitment)

        status = "broadcast" if txid else "queued"
        receipt = self.store.insert(
            commitment, mode, shielded, opid, txid, status=status
        )
        self._remember_shielded(shielded)
        return _public(receipt)

    def _anchor_tx(self, commitment: str) -> tuple[str | None, str | None, str, bool]:
        """Return (opid, txid, mode, shielded) for one commitment.

        Mode B tries the commitment in the encrypted memo first; if the
        network refuses Orchard actions it retries as mode A. The
        transparent constant-amount beacon is used ONLY when the node
        itself will not make a shielded spend — no spendable notes is a
        503, not a fallback. With the transparent fallback there is no
        nullifier to burn, and the 409 replay check is the only replay
        protection left (docs/ZANCHOR_API.md).
        """
        mode = self.mode
        if self.mode == "B":
            try:
                return self._send_shielded(commitment), None, "B", True
            except RpcError as exc:
                logger.warning("mode B refused (%s); retrying as mode A", exc)
                mode = "A"
        try:
            opid = self._send_shielded(None)
            return opid, None, mode, True
        except RpcError as exc:
            # The node will not make a shielded spend at all (e.g. Orchard
            # actions disabled). A constant-amount transparent beacon is
            # the honest fallback — and the receipt must say so.
            if self.recipient_taddr:
                logger.warning(
                    "shielded spends refused (%s); transparent fallback", exc
                )
                return None, self._send_transparent(), "A", False
            raise HTTPException(503, f"no spendable note left ({exc})")

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

    def _send_transparent(self) -> str:
        assert self.rpc is not None
        return self.rpc.send_transparent(self.recipient_taddr, self.amount)

    # -- worker ------------------------------------------------------------

    def poll_pending(self) -> None:
        if self.rpc is None:
            return
        for receipt in self.store.unconfirmed():
            try:
                self._advance(receipt)
            except RpcError as exc:
                logger.warning("receipt %s: %s", receipt["receipt_id"], exc)

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
                return
            return
        if receipt["status"] == "broadcast" and receipt["txid"]:
            tx = self.rpc.transaction(receipt["txid"])
            height = tx.get("blockheight") or _block_height(
                self.rpc, tx.get("blockhash")
            )
            if height:
                self.store.set_confirmed(
                    rid,
                    int(height),
                    _iso(
                        tx.get("blocktime")
                        or _block_time(self.rpc, tx.get("blockhash"))
                    ),
                )


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
    return {
        "receipt_id": receipt["receipt_id"],
        "commitment": receipt["commitment"],
        "status": receipt["status"],
        "mode": receipt["mode"],
        "shielded": receipt["shielded"],
        "txid": receipt.get("txid"),
        "height": receipt.get("height"),
        "anchored_at": receipt.get("anchored_at"),
    }


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
        if service.store.by_commitment(commitment) is not None:
            raise HTTPException(409, "commitment already anchored")
        try:
            return service.anchor(commitment)
        except HTTPException:
            raise

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str) -> dict[str, Any]:
        row = service.store.get(receipt_id)
        if row is None:
            raise HTTPException(404, "unknown receipt")
        return _public(row)

    @app.get("/chain/tx/{txid}")
    def chain_tx(txid: str) -> dict[str, Any]:
        if service.rpc is None:
            raise HTTPException(503, "no node")
        try:
            tx = service.rpc.transaction(txid)
        except RpcError as exc:
            if exc.code in (-5, -8):  # no such transaction / invalid address
                raise HTTPException(404, "node does not know this transaction")
            raise HTTPException(503, f"node error: {exc.message}")
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
        }

    return app


app = build_app()
