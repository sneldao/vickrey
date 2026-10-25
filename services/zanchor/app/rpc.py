"""zcashd wallet JSON-RPC client (stdlib only).

The anchor service talks to ONE node: the same wallet that builds the
anchor transactions. That is what lets /chain/tx answer
proof-of-existence from the node's own records (gettransaction works for
transactions the wallet built, without txindex) instead of handing an
anchor txid to a third-party explorer.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from base64 import b64encode
from typing import Any


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ZcashRpc:
    def __init__(self, url: str, timeout: float = 120.0) -> None:
        # Split credentials off the URL: Python 3.12's urllib cannot
        # connect to URLs containing user:pass@ (it fails at the socket
        # layer). The Basic header below is what the node actually sees.
        raw = url.rstrip("/") + "/"
        at = raw.rfind("@")
        scheme_end = raw.find("://")
        if at != -1 and at > scheme_end:
            cred = raw[scheme_end + 3 : at]
            self.url = raw[: scheme_end + 3] + raw[at + 1 :]
            self._auth_cached = b64encode(cred.encode()).decode()
        else:
            self.url = raw
            self._auth_cached = None
        self.timeout = timeout
        self._counter = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        with self._lock:
            self._counter += 1
            req_id = self._counter
        body = json.dumps(
            {"jsonrpc": "1.0", "id": req_id, "method": method, "params": params or []}
        ).encode()
        req = urllib.request.Request(self.url, data=body, method="POST")
        req.add_header("Authorization", f"Basic {self._auth}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            out = json.load(resp)
        if out.get("error"):
            err = out["error"]
            raise RpcError(err.get("code", -1), str(err.get("message", err)))
        return out.get("result")

    @property
    def _auth(self) -> str:
        if self._auth_cached is None:
            return ""
        return self._auth_cached

    # -- convenience -----------------------------------------------------

    def ping(self) -> None:
        self.call("ping")

    def block_count(self) -> int:
        return int(self.call("getblockcount"))

    def note_count(self) -> int:
        # 6.x removed z_listshieldedreceivednotes; the verified note count
        # is the spendability signal (dedicated wallet: every verified note
        # is an anchor note).
        counts = self.call("z_getnotescount")
        return sum(
            int(counts.get(pool, 0) or 0) for pool in ("sprout", "sapling", "orchard")
        )

    def notes_available(self) -> int:
        return self.note_count()

    def transparent_balance(self) -> float:
        return float(self.call("getbalance"))

    def transparent_address(self) -> str:
        return self.call("getnewaddress")

    def send_shielded(
        self,
        from_zaddr: str,
        to_zaddr: str,
        amount: str,
        fee: str,
        memo: str | None = None,
    ) -> str:
        recipient: dict[str, Any] = {"address": to_zaddr, "amount": amount}
        if memo is not None:
            recipient["memo"] = memo
        return str(self.call("z_sendmany", [from_zaddr, [recipient], 10, fee]))

    def send_transparent(self, to_taddr: str, amount: str) -> str:
        return str(self.call("sendtoaddress", [to_taddr, amount]))

    def operation_status(self, opid: str) -> dict[str, Any]:
        # 6.x takes a list of operation ids as its single parameter.
        return self.call("z_getoperationstatus", [[opid]])[0]

    def transaction(self, txid: str) -> dict[str, Any]:
        return self.call("gettransaction", [txid])
