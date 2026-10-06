#!/usr/bin/env python3
"""Stand-in for the two Hornet GETs the Day 2 ledger uses.

POST /_control registers a tagged-data block. GET /api/core/v2/blocks/<id>
and GET /api/core/v2/blocks/<id>/metadata return it. This process never
stands in for a real Tangle; scripts/demo_day2.sh uses it so the verify
and tamper path can run without the remote Day 1 node.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

BLOCKS: dict[str, dict] = {}


def normalize(block_id: str) -> str:
    text = unquote(block_id).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    return text.lower()


def hex_utf8(text: str) -> str:
    return "0x" + text.encode("utf-8").hex()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-hornet] {self.address_string()} {fmt % args}", flush=True)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise TypeError("JSON object required")
        return body

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/_control":
            self._send(404, {"error": "not found"})
            return
        try:
            body = self._read_json()
            block_id = body["blockId"]
            tag = body["tag"]
            message = body["message"]
        except (KeyError, TypeError, ValueError) as exc:
            self._send(400, {"error": str(exc)})
            return
        metadata: dict = {
            "blockId": block_id,
            "isSolid": bool(body.get("isSolid", True)),
        }
        if "referencedByMilestoneIndex" in body:
            if body["referencedByMilestoneIndex"] is not None:
                metadata["referencedByMilestoneIndex"] = body[
                    "referencedByMilestoneIndex"
                ]
        else:
            metadata["referencedByMilestoneIndex"] = 1
        BLOCKS[normalize(block_id)] = {
            "block": {
                "protocolVersion": 2,
                "parents": [],
                "payload": {
                    "type": 5,
                    "tag": hex_utf8(tag),
                    "data": hex_utf8(json.dumps(message)),
                },
                "nonce": "1",
            },
            "metadata": metadata,
        }
        self._send(200, {"ok": True, "blockId": block_id})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        prefix = "/api/core/v2/blocks/"
        if not path.startswith(prefix):
            self._send(404, {"error": "not found"})
            return
        rest = path[len(prefix) :]
        if rest.endswith("/metadata"):
            block_id = rest[: -len("/metadata")]
            kind = "metadata"
        else:
            block_id = rest.rstrip("/")
            kind = "block"
        record = BLOCKS.get(normalize(block_id))
        if record is None:
            self._send(404, {"error": "block not found"})
            return
        self._send(200, record[kind])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14266)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock hornet on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
