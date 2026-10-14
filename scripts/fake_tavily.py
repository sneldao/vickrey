#!/usr/bin/env python3
"""A fake Tavily, so the context route can be exercised without a key.

Standalone and importable; `scripts/demo_context.sh` runs it on a port, and the
ledger's own tests use `httpx.MockTransport` instead.

    python3 scripts/fake_tavily.py --port 8099
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RESULTS = [
    {
        "title": "RSPB: robin identification and habitat",
        "url": "https://www.rspb.org.uk/birds-and-wildlife/robin",
        "content": "The robin is one of the most recognisable UK birds, found in woodland, hedgerows and gardens across the country.",
        "score": 0.93,
    },
    {
        "title": "Hackney Marshes bird log — October",
        "url": "https://example.org/hackney-marshes-log",
        "content": "Two robins reported this month along the railway cutting, plus a pair nesting in the hedge by the footbridge.",
        "score": 0.81,
    },
    {
        "title": "London wildlife sightings this week",
        "url": "https://example.net/london-sightings",
        "content": "Several reports of European robin across east London, typically close to water and in dense hedging.",
        "score": 0.74,
    },
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[fake-tavily] {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        """A health probe, so the demo script can wait for readiness."""
        if self.path.rstrip("/") in ("", "/health"):
            self._send(200, {"status": "ok", "service": "fake-tavily"})
            return
        self._send(404, {"detail": {"error": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            body = {}
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send(401, {"detail": {"error": "missing or invalid API key"}})
            return
        query = body.get("query", "")
        print(f"[fake-tavily] query: {query}", flush=True)
        # Echo the query back so the UI shows exactly what was asked.
        self._send(
            200,
            {
                "query": query,
                "answer": (
                    "There are recent public reports of this species nearby. "
                    "Treat them as context, not as verification of your record."
                ),
                "results": RESULTS[: int(body.get("max_results", 5) or 5)],
                "response_time": 0.42,
                "usage": {"credits": 1},
            },
        )

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake tavily on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
