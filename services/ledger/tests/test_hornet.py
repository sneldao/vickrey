from __future__ import annotations

import httpx
from app.hornet import HornetClient


def test_fetch_uses_core_v2_block_and_metadata():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/metadata"):
            return httpx.Response(
                200,
                json={"isSolid": True, "referencedByMilestoneIndex": 4},
            )
        return httpx.Response(
            200,
            json={
                "protocolVersion": 2,
                "payload": {"type": 5, "tag": "0x61", "data": "0x7b7d"},
            },
        )

    client = HornetClient(
        "http://iota-hornet:14265", transport=httpx.MockTransport(handler)
    )
    try:
        fetched = client.fetch("0xabc")
    finally:
        client.close()

    assert seen == [
        "/api/core/v2/blocks/0xabc",
        "/api/core/v2/blocks/0xabc/metadata",
    ]
    assert fetched.block_status == 200
    assert fetched.metadata is not None
    assert fetched.metadata["isSolid"] is True
    assert fetched.error is None


def test_fetch_connection_error_does_not_look_like_a_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = HornetClient(
        "http://127.0.0.1:14265", transport=httpx.MockTransport(handler)
    )
    try:
        fetched = client.fetch("0xabc")
    finally:
        client.close()

    assert fetched.error
    assert fetched.block is None
    assert fetched.metadata is None
