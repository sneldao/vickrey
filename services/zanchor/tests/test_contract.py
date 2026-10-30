"""Contract tests for the zanchor service (docs/ZANCHOR_API.md).

A fake RPC stands in for zcashd; no node is needed. The shapes and the
replay/no-enumeration rules are pinned by the contract, so these tests
fail on any drift between the two.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.rpc import RpcError


class FakeRpc:
    """Just enough zcashd for the service: shielded sends, ops, txs."""

    def __init__(self) -> None:
        self.notes = 3
        self.anchors: list[dict] = []
        self._n = 0
        self.net = "regtest"

    def ping(self) -> None:
        pass

    def block_count(self) -> int:
        return 100

    def network(self) -> str:
        return self.net

    def notes_available(self) -> int:
        return self.notes

    def send_shielded(self, from_zaddr, to_zaddr, amount, fee, memo=None) -> str:
        self._n += 1
        self.notes -= 1
        self.anchors.append(
            {
                "amount": amount,
                "memo": memo,
                "txid": f"tx_{self._n:064d}",
                "height": 101,
                "confirmations": 5,
            }
        )
        return f"op_{self._n}"

    def operation_status(self, opid) -> dict:
        n = int(opid.split("_")[1])
        if 0 < n <= len(self.anchors):
            return {
                "status": "success",
                "result": {"txid": self.anchors[n - 1]["txid"]},
            }
        return {"status": "queued"}

    def _find(self, txid) -> dict:
        for a in self.anchors:
            if a.get("txid") == txid:
                return a
        raise RpcError(-5, "Transaction not eligible for re-broadcast / unknown")

    def transaction(self, txid) -> dict:
        a = self._find(txid)
        if a.get("gone"):
            raise RpcError(-5, "Transaction not eligible for re-broadcast / unknown")
        return {
            "txid": txid,
            "blockheight": a.get("height", 101),
            "confirmations": a.get("confirmations", 5),
            "blocktime": 1792900000,
            "blockhash": "fh" * 32,
        }

    def view_transaction(self, txid) -> dict:
        a = self._find(txid)
        memo = a.get("memo")
        outputs = []
        if memo:
            # The wallet returns the full 512-byte memo field, zero-padded.
            outputs.append({"type": "orchard", "memo": memo.ljust(1024, "0")})
        return {"outputs": outputs}


def _commitment(n: int) -> str:
    return f"{n:064x}"


def make_app(tmp_path, monkeypatch, mode: str | None = "A"):
    monkeypatch.setenv("ZANCHOR_DB", str(tmp_path / "zanchor.db"))
    if mode is None:
        monkeypatch.delenv("ZANCHOR_MODE", raising=False)
    else:
        monkeypatch.setenv("ZANCHOR_MODE", mode)
    monkeypatch.setenv("ZANCHOR_ANCHOR_ZADDR", "u:anchor")
    monkeypatch.setenv("ZANCHOR_RECIPIENT_ZADDR", "u:verifier")

    from app.main import AnchorService, build_app

    app = build_app()
    service: AnchorService = app.state.service
    service.rpc = FakeRpc()
    return app, service


def confirm(c, service, rid: str) -> None:
    for _ in range(3):
        service.poll_pending()
    assert c.get(f"/receipts/{rid}").json()["status"] == "confirmed"


def test_default_mode_is_b_and_invalid_mode_fails(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode=None)
    assert service.mode == "B"
    with TestClient(app) as c:
        r = c.post("/anchor", json={"commitment": _commitment(7)})
        assert r.status_code == 202
        assert r.json()["mode"] == "B"
        assert r.json()["shielded"] is True
        assert service.rpc.anchors[0]["memo"] == "00" + _commitment(7)
        assert c.get("/health").json()["mode"] == "B"

    monkeypatch.setenv("ZANCHOR_MODE", "C")
    monkeypatch.setenv("ZANCHOR_DB", str(tmp_path / "other.db"))
    from app.main import build_app

    with pytest.raises(ValueError):
        build_app()


def test_mode_b_refusal_does_not_downgrade(tmp_path, monkeypatch):
    # A node that refuses the memo send must get a 503 — never a quieter
    # transaction and never a silent mode-A anchor.
    app, service = make_app(tmp_path, monkeypatch, mode="B")
    rpc = service.rpc

    def refuse(*a, **k):
        raise RpcError(-8, "Orchard actions disabled")

    rpc.send_shielded = refuse
    with TestClient(app) as c:
        r = c.post("/anchor", json={"commitment": _commitment(8)})
        assert r.status_code == 503
        assert "downgraded" in r.json()["detail"]
        assert rpc.anchors == [], "no transaction may be attempted"
        assert c.get("/receipts/anything").status_code == 404


def test_mode_a_refusal_does_not_downgrade(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode="A")

    def refuse(*a, **k):
        raise RpcError(-1, "shielded spends unsupported")

    service.rpc.send_shielded = refuse
    with TestClient(app) as c:
        r = c.post("/anchor", json={"commitment": _commitment(9)})
        assert r.status_code == 503
        assert service.rpc.anchors == []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode="A")
    with TestClient(app) as c:
        yield c, service


@pytest.fixture()
def client_b(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode="B")
    with TestClient(app) as c:
        yield c, service


def test_health_shape(client):
    c, svc = client
    h = c.get("/health").json()
    assert h["status"] == "ok"
    assert h["node"] == "ok"
    assert h["mode"] == "A"
    assert h["shielded"] is True
    assert h["notes_available"] == 3
    assert h["network"] == "regtest"


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
    r = c.post("/anchor", json={"commitment": _commitment(4)})
    assert r.status_code == 503
    assert svc.rpc.anchors == []


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


# -- verify endpoint ------------------------------------------------------


def test_verify_mode_b_memo_verifies(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(11)}).json()["receipt_id"]
    confirm(c, svc, rid)
    r = c.get(f"/receipts/{rid}/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["receipt_id"] == rid
    assert body["commitment"] == _commitment(11)
    assert body["txid"] == svc.rpc.anchors[0]["txid"]
    assert body["height"] == 101
    assert body["confirmations"] == 5
    assert body["network"] == "regtest"
    assert body["transaction_verified"] is True
    assert body["commitment_verified"] is True
    assert body["binding"] == "encrypted_memo"
    assert body["verification_source"] == "service_wallet"
    assert body["reason"] == "commitment_in_encrypted_memo"


def test_verify_exact_unpadded_memo_also_matches(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(12)}).json()["receipt_id"]
    confirm(c, svc, rid)
    # Some wallets return the 33-byte memo without the 512-byte padding.
    svc.rpc.view_transaction = lambda t: {
        "outputs": [{"type": "orchard", "memo": "00" + _commitment(12)}]
    }
    assert c.get(f"/receipts/{rid}/verify").json()["commitment_verified"] is True


def test_verify_rejects_substring_and_wrong_memos(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(13)}).json()["receipt_id"]
    confirm(c, svc, rid)
    # The commitment embedded inside a longer payload is not a match —
    # no substring search, ever.
    svc.rpc.view_transaction = lambda t: {
        "outputs": [{"type": "orchard", "memo": ("00" + _commitment(13)) * 8}]
    }
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is True
    assert body["commitment_verified"] is False
    assert body["reason"] == "memo_mismatch"
    # A well-formed memo for a different commitment is also a mismatch.
    svc.rpc.view_transaction = lambda t: {
        "outputs": [
            {"type": "orchard", "memo": ("00" + _commitment(99)).ljust(1024, "0")}
        ]
    }
    assert c.get(f"/receipts/{rid}/verify").json()["commitment_verified"] is False


def test_verify_wrong_height_or_txid_fails(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(14)}).json()["receipt_id"]
    confirm(c, svc, rid)
    # Reorg: the transaction sits at a different height than the receipt.
    svc.rpc.anchors[0]["height"] = 107
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["commitment_verified"] is False
    assert body["reason"] == "height_mismatch"
    # The node no longer knowing the txid fails the same way.
    svc.rpc.anchors[0]["gone"] = True
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["reason"] == "transaction_not_on_node"


def test_verify_zero_or_missing_confirmations_fail(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(15)}).json()["receipt_id"]
    confirm(c, svc, rid)
    svc.rpc.anchors[0]["confirmations"] = 0
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["reason"] == "insufficient_confirmations"


def test_verify_mode_a_is_never_commitment_verified(client):
    c, svc = client
    rid = c.post("/anchor", json={"commitment": _commitment(16)}).json()["receipt_id"]
    confirm(c, svc, rid)
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is True
    assert body["commitment_verified"] is False
    assert body["binding"] == "verifier_record"
    assert body["reason"] == "verifier_record_only"


def test_verify_pending_receipt_is_not_confirmed(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(17)}).json()["receipt_id"]
    # The verify path advances the receipt itself (queued -> broadcast ->
    # confirmed) through the same locked worker path.
    body = c.get(f"/receipts/{rid}/verify").json()
    while c.get(f"/receipts/{rid}").json()["status"] != "confirmed":
        body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is True
    assert body["commitment_verified"] is True


def test_verify_unknown_receipt_404_and_no_rpc_503(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode="B")
    with TestClient(app) as c:
        assert c.get("/receipts/rec_nope/verify").status_code == 404
        service.rpc = None
        rid_row = service.store.insert(_commitment(18), "B", True, None)
        assert c.get(f"/receipts/{rid_row['receipt_id']}/verify").status_code == 503


def test_verify_unknown_network_fails_proof(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(19)}).json()["receipt_id"]
    confirm(c, svc, rid)
    svc.rpc.net = "signet"
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["network"] == "unknown"
    assert body["commitment_verified"] is False
    svc.rpc.net = "test"
    assert c.get(f"/receipts/{rid}/verify").json()["network"] == "testnet"


# -- disclosure ------------------------------------------------------------


def test_disclosure_success_writes_one_audit_line(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(21)}).json()["receipt_id"]
    confirm(c, svc, rid)
    r = c.post(f"/receipts/{rid}/disclosure", json={"purpose": "  grant review  "})
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "vickrey.receipt-disclosure/1"
    assert body["receipt"]["receipt_id"] == rid
    assert body["verification"]["commitment_verified"] is True
    assert svc.store.disclosure_count(rid) == 1
    r = c.post(f"/receipts/{rid}/disclosure", json={"purpose": "audit"})
    assert svc.store.disclosure_count(rid) == 2


def test_disclosure_rejected_or_unknown_writes_no_audit(client_b, client):
    c, svc = client_b
    # Unverified (mode A-style record): 409, no audit row.
    unverified = svc.store.insert(_commitment(22), "A", True, None)
    r = c.post(
        f"/receipts/{unverified['receipt_id']}/disclosure",
        json={"purpose": "curiosity"},
    )
    assert r.status_code == 409
    assert svc.store.disclosure_count(unverified["receipt_id"]) == 0
    # Unknown id: 404.
    assert (
        c.post("/receipts/rec_nope/disclosure", json={"purpose": "x"}).status_code
        == 404
    )
    # Bad purposes: 400.
    for bad in ({}, {"purpose": ""}, {"purpose": "   "}, {"purpose": "x" * 201}):
        assert (
            c.post(
                f"/receipts/{unverified['receipt_id']}/disclosure", json=bad
            ).status_code
            == 400
        )


def test_no_keys_or_enumeration_in_responses(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(23)}).json()["receipt_id"]
    confirm(c, svc, rid)
    for path in (
        f"/receipts/{rid}",
        f"/receipts/{rid}/verify",
        "/health",
    ):
        body = c.get(path).text.lower()
        for leak in ("private_key", "jwk", "viewing_key", "spending", "secret"):
            assert leak not in body, f"{path} leaked {leak}"
        # The raw memo bytes are never echoed; "encrypted_memo" is the
        # contract's binding label, not memo content.
        assert '"memo"' not in body.replace("encrypted_memo", "")
    assert c.get("/receipts").status_code == 404
    assert c.get("/receipts/audit").status_code == 404


# -- concurrency -----------------------------------------------------------


def test_concurrent_anchors_are_serialized(client_b):
    c, svc = client_b
    results: list[int] = []
    barrier = threading.Barrier(3)

    def post(n: int) -> None:
        barrier.wait()
        r = c.post("/anchor", json={"commitment": _commitment(n)})
        results.append(r.status_code)

    threads = [
        threading.Thread(target=post, args=(30,)),
        threading.Thread(target=post, args=(31,)),
    ]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()
    # Exactly one anchor was created; the second found it in flight.
    assert sorted(results) == [202, 503]
    assert len(svc.rpc.anchors) == 1
    assert len(svc.store.unconfirmed()) == 1


def test_verify_txid_mismatch_in_node_answer_fails(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(40)}).json()["receipt_id"]
    confirm(c, svc, rid)
    # The node answers a different txid than the receipt holds.
    orig = svc.rpc.transaction
    svc.rpc.transaction = lambda t: {**orig(t), "txid": "aa" * 32}
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["commitment_verified"] is False
    assert body["reason"] == "txid_mismatch"


def test_verify_boolean_height_or_confirmations_fail(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(41)}).json()["receipt_id"]
    confirm(c, svc, rid)
    orig = svc.rpc.transaction
    svc.rpc.transaction = lambda t: {**orig(t), "confirmations": True}
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["reason"] == "insufficient_confirmations"
    svc.rpc.transaction = lambda t: {**orig(t), "blockheight": True}
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False


def test_verify_unknown_network_fails_both_booleans(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(42)}).json()["receipt_id"]
    confirm(c, svc, rid)
    svc.rpc.net = "weirdchain"
    body = c.get(f"/receipts/{rid}/verify").json()
    assert body["transaction_verified"] is False
    assert body["commitment_verified"] is False
    assert body["reason"] == "network_unknown"


def test_worker_survives_transport_outage(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(43)}).json()["receipt_id"]
    orig = svc.rpc.operation_status

    def outage(opid):
        raise OSError("connection reset")

    svc.rpc.operation_status = outage
    # poll_pending must not raise or kill the worker on transport errors.
    svc.poll_pending()
    svc.rpc.operation_status = orig
    svc.poll_pending()
    svc.poll_pending()
    assert c.get(f"/receipts/{rid}").json()["status"] == "confirmed"


def test_advance_needs_positive_confirmations(client_b):
    c, svc = client_b
    rid = c.post("/anchor", json={"commitment": _commitment(44)}).json()["receipt_id"]
    svc.poll_pending()  # queued -> broadcast
    svc.rpc.anchors[0]["confirmations"] = 0
    svc.poll_pending()
    assert c.get(f"/receipts/{rid}").json()["status"] == "broadcast"
    svc.rpc.anchors[0]["confirmations"] = 2
    svc.poll_pending()
    assert c.get(f"/receipts/{rid}").json()["status"] == "confirmed"


def test_expected_network_guard(tmp_path, monkeypatch):
    app, service = make_app(tmp_path, monkeypatch, mode="B")
    monkeypatch.setenv("ZANCHOR_EXPECTED_NETWORK", "regtest")
    service.expected_network = "regtest"
    service.rpc.net = "main"
    with TestClient(app) as c:
        r = c.post("/anchor", json={"commitment": _commitment(45)})
        assert r.status_code == 503
        assert "expected network" in r.json()["detail"]
        assert service.rpc.anchors == []


def test_miner_refuses_non_regtest_and_generates_bare():
    from app.mine_regtest import require_regtest

    class StubRpc:
        def __init__(self, net):
            self.net = net
            self.calls = []

        def network(self):
            return self.net

        def call(self, method, params):
            self.calls.append((method, params))
            return 1

    rpc = StubRpc("main")
    with pytest.raises(SystemExit):
        require_regtest(rpc)
    assert rpc.calls == [], "no wallet/node call may run before regtest proof"

    reg = StubRpc("regtest")
    require_regtest(reg)
    reg.call("generate", [1])
    assert reg.calls == [("generate", [1])]
