#!/usr/bin/env python3
"""Stand-in for the Messages API insert path, so the field loop runs locally.

In production the field client POSTs an anchor to iota-messages-api, which
writes the tagged-data block to Hornet; the evidence ledger then reads that
block back independently. This relay keeps the same shape:

    POST /ingest  {blockId, tag, message}
      1. register the block with the mock Hornet (``POST /_control``)
      2. POST the same anchor to the ledger, which reads Hornet on its own
      3. return the ledger's message row

It exists so ``scripts/demo_field.sh`` and the browser smoke check can exercise
the client -> Messages API -> Hornet -> ledger path with no remote node. It is
not the Messages API and does not replace it.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULTS = {"hornet": "http://127.0.0.1:14266", "ledger": "http://127.0.0.1:8088"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    hornet_url = DEFAULTS["hornet"]
    ledger_url = DEFAULTS["ledger"]

    def log_message(self, fmt: str, *args) -> None:
        print(f"[anchor-relay] {fmt % args}", flush=True)

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
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

    def _post(self, url: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"detail": raw}

    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server naming
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.rstrip("/") == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "service": "anchor-relay",
                    "hornet": self.hornet_url,
                    "ledger": self.ledger_url,
                },
            )
            return
        self._send(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        if self.path.rstrip("/") != "/ingest":
            self._send(404, {"detail": "not found"})
            return
        try:
            body = self._read_json()
            block_id = str(body["blockId"])
            tag = str(body["tag"])
            message = body["message"]
        except (KeyError, TypeError, ValueError) as exc:
            self._send(400, {"detail": f"blockId, tag and message are required: {exc}"})
            return

        register = {
            "blockId": block_id,
            "tag": tag,
            "message": message,
            "isSolid": True,
            "referencedByMilestoneIndex": int(body.get("milestone", 42)),
        }
        status, hornet_body = self._post(f"{self.hornet_url}/_control", register)
        if status >= 300:
            self._send(
                502, {"detail": f"Hornet register failed: {status} {hornet_body}"}
            )
            return

        ingest = {
            "blockId": block_id,
            "tag": tag,
            "message": message,
            "hornetStatus": 201,
        }
        status, ledger_body = self._post(f"{self.ledger_url}/ingest", ingest)
        self.log_message(
            "anchored %s -> ledger %s %s",
            block_id[:12],
            status,
            ledger_body.get("status"),
        )
        # Pass the ledger's own status code and row straight through.
        self._send(status, ledger_body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--hornet", default=DEFAULTS["hornet"])
    parser.add_argument("--ledger", default=DEFAULTS["ledger"])
    args = parser.parse_args()
    Handler.hornet_url = args.hornet.rstrip("/")
    Handler.ledger_url = args.ledger.rstrip("/")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"anchor relay on http://{args.host}:{args.port} "
        f"(hornet {Handler.hornet_url}, ledger {Handler.ledger_url})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
