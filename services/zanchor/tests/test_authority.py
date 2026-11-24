"""Authority and crash-safety tests for the hardened zanchor pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import Receipts
from app.rpc import RpcError
from test_contract import FakeRpc, _commitment, confirm, make_app, post_anchor


class Crash(BaseException):
    """Simulated process death, not an ordinary request exception."""


def _digest(commitment: str) -> str:
    return hashlib.sha256(commitment.encode()).hexdigest()


def _events(store: Receipts, receipt_id: str) -> list[sqlite3.Row]:
    store._conn.row_factory = sqlite3.Row
    return store._conn.execute(
        "SELECT * FROM anchor_events WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()


def test_additive_migration_preserves_old_receipts_and_audit(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE receipts (
            receipt_id TEXT PRIMARY KEY,
            commitment TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            shielded INTEGER NOT NULL,
            opid TEXT,
            txid TEXT,
            height INTEGER,
            anchored_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE disclosure_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            purpose TEXT NOT NULL
        );
        INSERT INTO receipts VALUES
            ('rec_old', '11' || printf('%062d', 0), 'confirmed', 'B', 1,
             'op_old', 'tx_old', 42, '2026-01-01T00:00:00Z', '2025-01-01T00:00:00Z');
        INSERT INTO receipts VALUES
            ('rec_failed', '22' || printf('%062d', 0), 'failed', 'A', 1,
             NULL, NULL, NULL, NULL, '2025-01-01T00:00:00Z');
        INSERT INTO disclosure_audit (receipt_id, created_at, purpose)
            VALUES ('rec_old', '2026-01-01T00:00:00Z', 'legacy audit');
        """
    )
    conn.commit()
    conn.close()

    store = Receipts(path)
    columns = {
        row["name"] for row in store._conn.execute("PRAGMA table_info(receipts)")
    }
    assert {
        "worker_id",
        "submitter_id",
        "lease_expires_at",
        "updated_at",
        "error",
    } <= columns
    old = store.get("rec_old")
    assert old["status"] == "confirmed"
    assert old["txid"] == "tx_old"
    assert old["height"] == 42
    assert old["updated_at"] == old["created_at"]
    assert store.get("rec_failed")["status"] == "failed"
    assert store.disclosure_count("rec_old") == 1
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()


def test_crash_before_rpc_leaves_submitting_then_reconciles_without_send(
    tmp_path, monkeypatch
):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")

    def crash(*args, **kwargs):
        raise Crash

    monkeypatch.setattr(svc, "_anchor_tx", crash)
    with pytest.raises(Crash):
        svc.anchor(_commitment(101), "crash-before-rpc", _digest("before"))
    row = svc.store.unconfirmed()[0]
    assert row["status"] == "submitting"
    assert row["opid"] is None
    assert row["worker_id"] == svc.worker_id
    assert row["lease_expires_at"] > time.time()
    assert svc.rpc.anchors == []

    svc.poll_pending()  # an unexpired submission lease cannot be stolen
    assert svc.store.get(row["receipt_id"])["status"] == "submitting"
    assert svc.store.expire_submitting_leases(row["lease_expires_at"] + 1) == 1
    svc.poll_pending()
    row = svc.store.get(row["receipt_id"])
    assert row["status"] == "reconciling"
    assert row["opid"] is None
    assert svc.rpc.anchors == []


def test_crash_after_rpc_before_opid_persistence_never_resends(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    original = svc.store.record_opid

    def crash(*args, **kwargs):
        raise Crash

    monkeypatch.setattr(svc.store, "record_opid", crash)
    with pytest.raises(Crash):
        svc.anchor(_commitment(102), "crash-after-rpc", _digest("after"))
    row = svc.store.unconfirmed()[0]
    assert row["status"] == "submitting"
    assert row["opid"] is None
    assert len(svc.rpc.anchors) == 1

    svc.store.expire_submitting_leases(row["lease_expires_at"] + 1)
    monkeypatch.setattr(svc.store, "record_opid", original)
    for _ in range(3):
        svc.poll_pending()
    row = svc.store.get(row["receipt_id"])
    assert row["status"] == "reconciling"
    assert row["opid"] is None
    assert len(svc.rpc.anchors) == 1


def test_stale_known_opid_is_reconciled_across_store_instances(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    from app.main import AnchorService

    receipt = svc.anchor(_commitment(103), "stale-known-opid", _digest("stale"))
    assert receipt["status"] == "queued"
    assert svc.store.get(receipt["receipt_id"])["opid"] == "op_1"
    svc.store._conn.execute(
        "UPDATE receipts SET status='submitting', worker_id='dead-worker',"
        " lease_expires_at=0 WHERE receipt_id=?",
        (receipt["receipt_id"],),
    )
    svc.store._conn.commit()

    store2 = Receipts(str(tmp_path / "zanchor.db"))
    svc2 = AnchorService(svc.rpc, store2)
    svc2.poll_pending()
    assert store2.get(receipt["receipt_id"])["status"] == "broadcast"
    svc2.poll_pending()
    assert store2.get(receipt["receipt_id"])["status"] == "confirmed"
    assert len(svc.rpc.anchors) == 1
    store2.close()


def test_idempotent_raw_byte_replay_conflict_and_key_validation(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="A")
    idem = "idem-raw-bytes-001"
    body = json.dumps({"commitment": _commitment(104)}, separators=(",", ":")).encode()
    headers = {"Idempotency-Key": idem}
    with TestClient(app) as c:
        first = c.post("/anchor", content=body, headers=headers)
        assert first.status_code == 202
        rid = first.json()["receipt_id"]
        replay = c.post("/anchor", content=body, headers=headers)
        assert replay.status_code == 202
        assert replay.json()["receipt_id"] == rid
        assert len(svc.rpc.anchors) == 1

        changed = b'{ "commitment": "' + _commitment(104).encode() + b'" }'
        assert c.post("/anchor", content=changed, headers=headers).status_code == 409
        assert (
            c.post("/anchor", content=b"not-json", headers=headers).status_code == 409
        )
        assert len(svc.rpc.anchors) == 1
        for bad in (None, "short", "has space", "x" * 129, "bad/key"):
            request_headers = {} if bad is None else {"Idempotency-Key": bad}
            assert (
                c.post("/anchor", content=body, headers=request_headers).status_code
                == 400
            )

        # A durable replay does not need a live node and performs no RPC.
        svc.rpc = None
        assert (
            c.post("/anchor", content=body, headers=headers).json()["receipt_id"] == rid
        )


def test_two_workers_cannot_both_submit_same_commitment(tmp_path, monkeypatch):
    app, svc1 = make_app(tmp_path, monkeypatch, mode="A")
    from app.main import AnchorService

    store2 = Receipts(str(tmp_path / "zanchor.db"))
    svc2 = AnchorService(svc1.rpc, store2)
    barrier = threading.Barrier(3)
    results = []

    def submit(svc, key):
        barrier.wait()
        try:
            results.append(
                svc.anchor(_commitment(105), key, _digest("workers"))["receipt_id"]
            )
        except HTTPException as exc:
            results.append(exc.status_code)

    threads = [
        threading.Thread(target=submit, args=(svc1, "worker-001")),
        threading.Thread(target=submit, args=(svc2, "worker-002")),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert len([result for result in results if isinstance(result, str)]) == 1
    assert 409 in results or 503 in results
    assert len(svc1.rpc.anchors) == 1
    assert len(svc1.store.unconfirmed()) == 1
    store2.close()


def test_definite_failure_retry_keeps_receipt_id_and_history(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    original = svc.rpc.send_shielded

    def refuse(*args, **kwargs):
        raise RpcError(-8, "SECRET_SENTINEL memo-xyzzy")

    svc.rpc.send_shielded = refuse
    with TestClient(app) as c:
        first = post_anchor(c, {"commitment": _commitment(106)}, "failure-001")
        assert first.status_code == 202
        assert first.json()["status"] == "failed"
        rid = first.json()["receipt_id"]
        before = len(_events(svc.store, rid))
        svc.rpc.send_shielded = original
        retry = post_anchor(c, {"commitment": _commitment(106)}, "failure-002")
        assert retry.status_code == 202
        assert retry.json()["receipt_id"] == rid
        assert retry.json()["status"] == "queued"
        assert len(_events(svc.store, rid)) > before
        replay = post_anchor(c, {"commitment": _commitment(106)}, "failure-001")
        assert replay.json()["receipt_id"] == rid
        assert len(svc.rpc.anchors) == 1
        confirm(c, svc, rid)


def test_uncertain_transport_is_reconciling_and_never_blindly_retried(
    tmp_path, monkeypatch
):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    original = svc.rpc.send_shielded

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("connection reset after node accepted request")

    svc.rpc.send_shielded = lost_response
    with TestClient(app) as c:
        first = post_anchor(
            c, {"commitment": _commitment(107)}, key="lost-response-001"
        )
        assert first.status_code == 202
        assert first.json()["status"] == "reconciling"
        rid = first.json()["receipt_id"]
        for _ in range(3):
            svc.poll_pending()
        assert len(svc.rpc.anchors) == 1
        assert svc.store.get(rid)["opid"] is None
        assert (
            post_anchor(
                c, {"commitment": _commitment(107)}, key="lost-response-002"
            ).status_code
            == 409
        )


def test_worker_lease_claim_is_conditional(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="A")
    receipt = svc.anchor(_commitment(108), "lease-claim-001", _digest("lease"))
    rid = receipt["receipt_id"]
    assert svc.store.claim_pending(rid, "worker-a", time.time() + 60) is not None
    assert svc.store.claim_pending(rid, "worker-b", time.time() + 60) is None
    svc.store._conn.execute(
        "UPDATE receipts SET lease_expires_at=0 WHERE receipt_id=?", (rid,)
    )
    svc.store._conn.commit()
    assert svc.store.claim_pending(rid, "worker-b", time.time() + 60) is not None
    svc.store.release_lease(rid, "worker-a")
    assert svc.store.get(rid)["worker_id"] == "worker-b"
    svc.store.release_lease(rid, "worker-b")
    assert svc.store.get(rid)["worker_id"] is None


def test_production_requires_token_and_protects_only_write_endpoints(
    tmp_path, monkeypatch
):
    from app.main import build_app

    monkeypatch.setenv("ZANCHOR_ENV", "production")
    monkeypatch.delenv("ZANCHOR_API_TOKEN", raising=False)
    monkeypatch.setenv("ZANCHOR_DB", str(tmp_path / "missing-token.db"))
    with pytest.raises(ValueError, match="ZANCHOR_API_TOKEN"):
        build_app()
    assert not (tmp_path / "missing-token.db").exists()

    token = "production-test-token"
    monkeypatch.setenv("ZANCHOR_API_TOKEN", token)
    monkeypatch.setenv("ZANCHOR_DB", str(tmp_path / "production.db"))
    monkeypatch.setenv("ZANCHOR_MODE", "B")
    monkeypatch.setenv("ZANCHOR_ANCHOR_ZADDR", "u:anchor")
    monkeypatch.setenv("ZANCHOR_RECIPIENT_ZADDR", "u:verifier")
    app = build_app()
    svc = app.state.service
    svc.rpc = FakeRpc()
    auth = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as c:
        body = {"commitment": _commitment(109)}
        assert (
            c.post(
                "/anchor", json=body, headers={"Idempotency-Key": "production-key-001"}
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/anchor",
                json=body,
                headers={
                    "Idempotency-Key": "production-key-001",
                    "Authorization": "Bearer wrong",
                },
            ).status_code
            == 401
        )
        created = c.post(
            "/anchor",
            json=body,
            headers={**auth, "Idempotency-Key": "production-key-001"},
        )
        assert created.status_code == 202
        rid = created.json()["receipt_id"]
        assert c.get(f"/receipts/{rid}").status_code == 200
        confirm(c, svc, rid)
        assert (
            c.post(
                f"/receipts/{rid}/disclosure", json={"purpose": "production review"}
            ).status_code
            == 401
        )
        assert (
            c.post(
                f"/receipts/{rid}/disclosure",
                json={"purpose": "production review"},
                headers=auth,
            ).status_code
            == 200
        )
        health = c.get("/health").json()
        assert health["env"] == "production"
        assert health["auth_required"] is True
        assert token not in json.dumps(health)


def test_demo_auth_is_disabled_even_if_token_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ZANCHOR_ENV", "demo")
    monkeypatch.setenv("ZANCHOR_API_TOKEN", "unused-demo-token")
    app, svc = make_app(tmp_path, monkeypatch, mode="A")
    svc.api_token = "unused-demo-token"
    with TestClient(app) as c:
        health = c.get("/health").json()
        assert health["env"] == "demo"
        assert health["auth_required"] is False
        assert (
            post_anchor(
                c,
                {"commitment": _commitment(110)},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 202
        )


def test_body_limit_covers_content_length_and_chunked_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("ZANCHOR_MAX_BODY_BYTES", "128")
    app, svc = make_app(tmp_path, monkeypatch, mode="A")
    body = json.dumps({"commitment": _commitment(111), "padding": "x" * 200}).encode()
    with TestClient(app) as c:
        assert (
            c.post(
                "/anchor", content=body, headers={"Idempotency-Key": "body-limit-001"}
            ).status_code
            == 413
        )

        def chunks():
            yield body[:60]
            yield body[60:]

        assert (
            c.post(
                "/anchor",
                content=chunks(),
                headers={"Idempotency-Key": "body-limit-002"},
            ).status_code
            == 413
        )
    assert svc.rpc.anchors == []
    assert svc.store.unconfirmed() == []


def test_anchor_quota_is_shared_fixed_window_and_replays_do_not_consume_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ZANCHOR_ANCHOR_QUOTA", "1")
    monkeypatch.setenv("ZANCHOR_QUOTA_WINDOW_SECONDS", "60")
    app, svc = make_app(tmp_path, monkeypatch, mode="A")
    with TestClient(app) as c:
        first = post_anchor(c, {"commitment": _commitment(112)}, key="quota-key-001")
        assert first.status_code == 202
        rid = first.json()["receipt_id"]
        confirm(c, svc, rid)
        assert (
            post_anchor(
                c, {"commitment": _commitment(112)}, key="quota-key-001"
            ).status_code
            == 202
        )
        assert (
            post_anchor(
                c, {"commitment": _commitment(113)}, key="quota-key-002"
            ).status_code
            == 429
        )
        conn = sqlite3.connect(str(tmp_path / "zanchor.db"))
        conn.execute("UPDATE rate_limits SET window_start=0 WHERE scope='anchor'")
        conn.commit()
        conn.close()
        assert (
            post_anchor(
                c, {"commitment": _commitment(113)}, key="quota-key-002"
            ).status_code
            == 202
        )


def test_disclosure_quota_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("ZANCHOR_DISCLOSURE_QUOTA", "1")
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    with TestClient(app) as c:
        rid = post_anchor(c, {"commitment": _commitment(114)}).json()["receipt_id"]
        confirm(c, svc, rid)
        assert (
            c.post(f"/receipts/{rid}/disclosure", json={"purpose": "first"}).status_code
            == 200
        )
        assert (
            c.post(
                f"/receipts/{rid}/disclosure", json={"purpose": "second"}
            ).status_code
            == 429
        )
        assert svc.store.disclosure_count(rid) == 1


def test_events_idempotency_and_disclosure_audit_are_immutable(tmp_path, monkeypatch):
    app, svc = make_app(tmp_path, monkeypatch, mode="B")
    with TestClient(app) as c:
        rid = post_anchor(c, {"commitment": _commitment(115)}).json()["receipt_id"]
        confirm(c, svc, rid)
        c.post(f"/receipts/{rid}/disclosure", json={"purpose": "immutable audit"})
    events = _events(svc.store, rid)
    assert events
    assert {row["event_type"] for row in events} >= {
        "submission_reserved",
        "opid_recorded",
        "broadcast",
        "confirmed",
    }
    event_columns = {
        row[1] for row in svc.store._conn.execute("PRAGMA table_info(anchor_events)")
    }
    assert event_columns == {
        "id",
        "receipt_id",
        "event_type",
        "created_at",
        "worker_id",
        "opid",
    }
    event_text = " ".join(str(value) for row in events for value in row)
    assert _commitment(115) not in event_text
    assert "memo" not in event_text.lower()

    for sql in (
        "UPDATE anchor_events SET event_type='tampered'",
        "DELETE FROM anchor_events",
        "UPDATE disclosure_audit SET purpose='tampered'",
        "DELETE FROM disclosure_audit",
        "UPDATE idempotency SET request_sha256='tampered'",
        "DELETE FROM idempotency",
        "INSERT OR REPLACE INTO anchor_events"
        " (id, receipt_id, event_type, created_at)"
        " SELECT id, receipt_id, event_type, created_at FROM anchor_events LIMIT 1",
        "INSERT OR REPLACE INTO disclosure_audit"
        " (id, receipt_id, created_at, purpose)"
        " SELECT id, receipt_id, created_at, purpose FROM disclosure_audit LIMIT 1",
        "INSERT OR REPLACE INTO idempotency"
        " (idempotency_key, request_sha256, receipt_id, created_at)"
        " SELECT idempotency_key, request_sha256, receipt_id, created_at"
        " FROM idempotency LIMIT 1",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            svc.store._conn.execute(sql)
        svc.store._conn.rollback()
