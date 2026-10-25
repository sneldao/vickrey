"""Contract tests for the zanchor service (docs/ZANCHOR_API.md).

A fake RPC stands in for zcashd; no node is needed. The shapes and the
replay/no-enumeration rules are pinned by the contract, so these tests
fail on any drift between the two.
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from app.rpc import RpcError


class FakeRpc:
    """Just enough zcashd for the service: shielded sends, ops, txs."""

    def __init__(self) -> None:
        self.notes = 3
        self.anchors: list[dict] = []
        self._n = 0

    def ping(self) -> None:
        pass

    def block_count(self) -> int:
        return 100

    def notes_available(self) -> int:
        return self.notes

    def send_shielded(self, from_zaddr, to_zaddr, amount, fee, memo=None) -> str:
        self._n += 1
        self.notes -= 1
        self.anchors.append(
            {"amount": amount, "memo": memo, "txid": f"tx_{self._n:064d}"}
        )
        return f"op_{self._n}"

    def send_transparent(self, to_taddr, amount) -> str:
        self._n += 1
        self.anchors.append(
            {"transparent": True, "amount": amount, "txid": f"tx_{self._n:064d}"}
        )
        return self.anchors[-1]["txid"]

    def operation_status(self, opid) -> dict:
        n = int(opid.split("_")[1])
        if 0 < n <= len(self.anchors):
            return {
                "jobStatus": "success",
                "result": {"txid": self.anchors[n - 1]["txid"]},
            }
        return {"jobStatus": "queued"}

    def transaction(self, txid) -> dict:
        if not any(a.get("txid") == txid for a in self.anchors):
            raise RpcError(-5, "Transaction not eligible for re-broadcast / unknown")
        return {
            "txid": txid,
            "blockheight": 101,
            "confirmations": 5,
            "blocktime": 1792900000,
            "blockhash": "fh" * 32,
        }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ZANCHOR_DB", str(tmp_path / "zanchor.db"))
    monkeypatch.setenv("ZANCHOR_MODE", "A")
    monkeypatch.setenv("ZANCHOR_ANCHOR_ZADDR", "u:anchor")
    monkeypatch.setenv("ZANCHOR_RECIPIENT_ZADDR", "u:verifier")
    monkeypatch.setenv("ZANCHOR_RECIPIENT_TADDR", "t:verifier")

    from app.main import AnchorService, build_app

    app = build_app()
    service: AnchorService = app.state.service
    service.rpc = FakeRpc()
    with TestClient(app) as c:
        yield c, service


def _commitment(n: int) -> str:
    return f"{n:064x}"


def test_health_shape(client):
    c, svc = client
    h = c.get("/health").json()
    assert h["status"] == "ok"
    assert h["node"] == "ok"
    assert h["mode"] == "A"
    assert h["shielded"] is True
    assert h["notes_available"] == 3


def test_anchor_returns_receipt_with_mode_and_shielded(client):
    c, svc = client
    r = c.post("/anchor", json={"commitment": _commitment(1)})
    assert r.status_code == 202
    body = r.json()
    assert body["receipt_id"].startswith("rec_")
    assert body["commitment"] == _commitment(1)
    assert body["status"] in ("queued", "broadcast", "confirmed")
    assert body["mode"] == "A"
    assert body["shielded"] is True
    assert body["height"] is None


def test_replay_is_409(client):
    c, svc = client
    assert c.post("/anchor", json={"commitment": _commitment(2)}).status_code == 202
    r = c.post("/anchor", json={"commitment": _commitment(2)})
    assert r.status_code == 409
    assert r.json()["detail"] == "commitment already anchored"
    # exactly one transaction was made for the commitment
    assert len(svc.rpc.anchors) == 1


def test_bad_commitment_is_400(client):
    c, _ = client
    assert c.post("/anchor", json={"commitment": "nope"}).status_code == 400
    assert (
        c.post("/anchor", json={"commitment": _commitment(3)[:63]}).status_code == 400
    )
    assert c.post("/anchor", json={}).status_code == 400


def test_no_notes_is_503_not_fallback(client):
    c, svc = client
    svc.rpc.notes = 0
    svc.recipient_taddr = "t:verifier"
    r = c.post("/anchor", json={"commitment": _commitment(4)})
    assert r.status_code == 503


def test_transparent_fallback_says_transparent(client, monkeypatch, tmp_path):
    c, svc = client
    from app.rpc import RpcError

    def refuse(*a, **k):
        raise RpcError(-1, "shielded spends unsupported")

    monkeypatch.setattr(svc.rpc, "send_shielded", refuse)
    svc.rpc.notes = 3  # notes exist; the node simply won't use them
    r = c.post("/anchor", json={"commitment": _commitment(5)})
    assert r.status_code == 202
    body = r.json()
    assert body["shielded"] is False, "fallback must say so on the receipt"
    assert body["mode"] == "A"
    assert body["txid"] is not None, "transparent path knows its txid immediately"
    assert c.get("/health").json()["shielded"] is False


def test_receipt_roundtrip_and_404(client):
    c, _ = client
    rid = c.post("/anchor", json={"commitment": _commitment(6)}).json()["receipt_id"]
    r = c.get(f"/receipts/{rid}")
    assert r.status_code == 200
    assert r.json()["receipt_id"] == rid
    assert c.get("/receipts/rec_nope").status_code == 404


def test_no_receipt_listing_endpoint(client):
    c, _ = client
    assert c.get("/receipts").status_code == 404


def test_chain_tx_shape_and_404(client):
    c, svc = client
    c.post("/anchor", json={"commitment": _commitment(8)})
    txid = svc.rpc.anchors[0]["txid"]
    r = c.get(f"/chain/tx/{txid}")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["height"] == 101
    assert body["confirmations"] == 5
    assert body["block_time"].endswith("Z")
    assert "commitment" not in body
    unknown = "ab" * 32
    assert c.get(f"/chain/tx/{unknown}").status_code in (404, 503)


def test_worker_advances_receipt_to_confirmed(client):
    c, svc = client
    rid = c.post("/anchor", json={"commitment": _commitment(7)}).json()["receipt_id"]
    for _ in range(3):
        svc.poll_pending()
    row = c.get(f"/receipts/{rid}").json()
    assert row["status"] == "confirmed"
    assert row["txid"] is not None
    assert row["height"] == 101
    assert row["anchored_at"].endswith("Z")
