#!/usr/bin/env python3
"""Stand-in for the shielded anchor service, pinned to docs/ZANCHOR_API.md.

It speaks the contract and nothing else:

    POST /anchor              {commitment} -> 202 receipt | 400 | 409 | 503
    GET  /receipts/{id}       verifier-held receipt | 404
    GET  /chain/tx/{txid}     proof of existence | 404
    GET  /health              status, node, mode, shielded, notes_available

There is deliberately no ``GET /receipts`` list endpoint.

**This is not a chain.** No Zcash node, no shielded pool, no transaction: the
txid is a hash of the commitment and the height is a counter. It exists so the
field client, the explorer, and ``scripts/demo_zcash.sh`` can run end to end
before ``services/zanchor`` does, and so that service has an executable
conformance fixture. The banner below is printed on start for that reason —
never present a run of this behind it as a chain.

``--transparent`` makes it report ``shielded: false``: the honest shape of the
fallback when a node refuses shielded spends. The clients must label that run
TRANSPARENT, and ``scripts/demo_zcash.sh`` checks they get the chance to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
MOCK_HEADER = "no-chain"  # every response says what answered
BANNER = (
    "MOCK ZANCHOR — no chain, no shielded pool, no transaction.\n"
    "Receipts here are a hash and a counter. services/zanchor is the real one."
)

# One anchor's state machine. Kept as a dict so the receipt can be rendered
# straight out of it, with the same keys the contract pins.
STATE: dict[str, dict] = {}
BY_COMMITMENT: dict[str, str] = {}
LOCK = threading.Lock()


class Settings:
    mode = "A"
    shielded = True
    notes = 3
    broadcast_delay = 0.5
    confirm_delay = 2.0
    base_height = 2_712_345


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def txid_for(commitment: str) -> str:
    # Deterministic, so the demo can assert on it. Not a transaction id.
    return hashlib.sha256(b"zanchor-mock:" + commitment.encode()).hexdigest()


def new_receipt_id() -> str:
    return "rec_mock_" + secrets.token_hex(8)


def advance(anchor: dict) -> None:
    """Move an anchor through queued -> broadcast -> confirmed, lazily.

    Called while holding LOCK. Timestamps, not timers, so a slow reader still
    sees every state it polls past."""
    if anchor["status"] == "queued" and time.time() >= anchor["_broadcast_at"]:
        anchor["status"] = "broadcast"
    if anchor["status"] == "broadcast" and time.time() >= anchor["_confirm_at"]:
        anchor["status"] = "confirmed"
        anchor["height"] = Settings.base_height + anchor["_index"]
        anchor["anchored_at"] = now_iso()
        anchor["_confirmed_at"] = time.time()


def public_receipt(anchor: dict) -> dict:
    """The receipt exactly as the contract shapes it — and nothing more."""
    advance(anchor)
    return {
        "receipt_id": anchor["receipt_id"],
        "commitment": anchor["commitment"],
        "status": anchor["status"],
        "mode": anchor["mode"],
        "shielded": anchor["shielded"],
        "txid": anchor["txid"] if anchor["status"] != "queued" else None,
        "height": anchor["height"],
        "anchored_at": anchor["anchored_at"],
    }


def advance_all() -> None:
    for anchor in STATE.values():
        advance(anchor)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-zanchor] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # The field client and the explorer run on other ports in a local demo.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("X-Vickrey-Mock", MOCK_HEADER)
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise TypeError("JSON object required")
        return body

    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server naming
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "node": "ok",
                    "mode": Settings.mode,
                    "shielded": Settings.shielded,
                    "notes_available": Settings.notes,
                    # A mock never claims a real chain — clients must not
                    # treat this network as a real proof.
                    "network": "mock",
                },
            )
            return
        if path == "/receipts":
            # Not in the contract, on purpose: no enumeration of anchors.
            self._send(404, {"detail": "not found"})
            return
        if path.startswith("/receipts/"):
            rest = unquote(path[len("/receipts/") :])
            verify = rest.endswith("/verify")
            receipt_id = rest[: -len("/verify")] if verify else rest
            with LOCK:
                for anchor in STATE.values():
                    if anchor["receipt_id"] != receipt_id:
                        continue
                    if not verify:
                        self._send(200, public_receipt(anchor))
                        return
                    advance(anchor)
                    confirmed = anchor["status"] == "confirmed"
                    # The mock exercises the UI but can never produce a
                    # real memo proof: network "mock" fails every VERIFIED.
                    self._send(
                        200,
                        {
                            "receipt_id": receipt_id,
                            "commitment": anchor["commitment"],
                            "txid": anchor["txid"],
                            "height": anchor["height"] if confirmed else None,
                            "confirmations": 1 if confirmed else None,
                            "network": "mock",
                            "transaction_verified": confirmed,
                            "commitment_verified": False,
                            "binding": "encrypted_memo"
                            if anchor["mode"] == "B"
                            else "verifier_record",
                            "verification_source": "service_wallet",
                            "reason": "mock_service_no_memo_proof",
                        },
                    )
                    return
            self._send(404, {"detail": "unknown receipt"})
            return
        if path.startswith("/chain/tx/"):
            txid = unquote(path[len("/chain/tx/") :]).lower()
            with LOCK:
                for anchor in STATE.values():
                    advance(anchor)
                    if anchor["txid"] != txid:
                        continue
                    if anchor["status"] != "confirmed":
                        # Broadcast but not mined: the node does not know it yet.
                        break
                    confirmations = 1 + int(
                        (time.time() - anchor["_confirmed_at"]) // 75
                    )
                    self._send(
                        200,
                        {
                            "txid": txid,
                            "exists": True,
                            "height": anchor["height"],
                            "confirmations": confirmations,
                            "block_time": anchor["anchored_at"],
                        },
                    )
                    return
            self._send(404, {"detail": "unknown transaction"})
            return
        self._send(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        path = urlparse(self.path).path.rstrip("/")
        if path.startswith("/receipts/") and path.endswith("/disclosure"):
            # A mock never has a memo proof — disclosures always refuse.
            self._send(
                409, {"detail": "commitment is not verified; nothing to disclose"}
            )
            return
        if urlparse(self.path).path.rstrip("/") != "/anchor":
            self._send(404, {"detail": "not found"})
            return
        try:
            body = self._read_json()
        except (TypeError, ValueError) as exc:
            self._send(400, {"detail": f"body must be a JSON object: {exc}"})
            return
        commitment = body.get("commitment")
        if not isinstance(commitment, str) or not HEX64.match(commitment):
            self._send(400, {"detail": "commitment must be 64 hex characters"})
            return
        commitment = commitment.lower()

        with LOCK:
            if commitment in BY_COMMITMENT:
                # Replay rejection. In this mock it is the ONLY replay
                # protection: there is no note and no nullifier to burn.
                self._send(409, {"detail": "commitment already anchored"})
                return
            if Settings.mode == "A" and Settings.notes <= 0:
                self._send(503, {"detail": "no spendable note left"})
                return
            if Settings.mode == "A":
                Settings.notes -= 1
            index = len(STATE)
            anchor = {
                "receipt_id": new_receipt_id(),
                "commitment": commitment,
                "status": "queued",
                "mode": Settings.mode,
                "shielded": Settings.shielded,
                "txid": txid_for(commitment),
                "height": None,
                "anchored_at": None,
                "_index": index,
                "_broadcast_at": time.time() + Settings.broadcast_delay,
                "_confirm_at": time.time()
                + Settings.broadcast_delay
                + Settings.confirm_delay,
                "_confirmed_at": None,
            }
            STATE[anchor["receipt_id"]] = anchor
            BY_COMMITMENT[commitment] = anchor["receipt_id"]
            receipt = public_receipt(anchor)

        self._send(202, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--mode", choices=("A", "B"), default="A")
    parser.add_argument(
        "--transparent",
        action="store_true",
        help="report shielded: false (the transparent-beacon fallback)",
    )
    parser.add_argument("--notes", type=int, default=3)
    parser.add_argument("--broadcast-delay", type=float, default=0.5)
    parser.add_argument("--confirm-delay", type=float, default=2.0)
    args = parser.parse_args()

    Settings.mode = args.mode
    Settings.shielded = not args.transparent
    Settings.notes = args.notes
    Settings.broadcast_delay = max(0.0, args.broadcast_delay)
    Settings.confirm_delay = max(0.0, args.confirm_delay)

    print(BANNER, flush=True)
    print(
        f"mock zanchor on http://{args.host}:{args.port} "
        f"(mode {Settings.mode}, shielded {Settings.shielded}, "
        f"notes {Settings.notes})",
        flush=True,
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
