from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import VerificationConflict, create_app, verify_stored
from tests.support import BLOCK_ID, MESSAGE, TAG, FakeHornet


def anchor(message=None, *, block_id=BLOCK_ID):
    return {
        "blockId": block_id,
        "tag": TAG,
        "message": MESSAGE if message is None else message,
        "hornetStatus": 201,
    }


def post_v2(client, body, key="idem-key-001", raw=None):
    return client.post(
        "/v2/ingest",
        content=json.dumps(body) if raw is None else raw,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": key,
        },
    )


def test_ingestion_never_overwrites_the_immutable_submission(client):
    http, _hornet = client
    first = http.post("/ingest", json=anchor()).json()
    changed = dict(MESSAGE, temperature=99)
    conflict = http.post("/ingest", json=anchor(changed))
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "block_id was already submitted with different content"
    )
    assert http.get(f"/messages/{BLOCK_ID}").json() == first

    assert http.post(f"/messages/{BLOCK_ID}/tamper", json={}).status_code == 200
    replay = http.post("/ingest", json=anchor())
    assert replay.status_code == 200
    assert replay.json()["payload_json"]["temperature"] == 999.9
    assert replay.json()["submission_payload_json"] == MESSAGE
    assert replay.json()["version"] > first["version"]


def test_v2_idempotency_replays_without_another_verification(tmp_path):
    hornet = FakeHornet()
    body = anchor()
    raw = json.dumps(body)
    with TestClient(
        create_app(database_path=str(tmp_path / "ledger.db"), hornet=hornet)
    ) as http:
        first = post_v2(http, body, raw=raw)
        assert first.status_code == 201
        assert len(hornet.calls) == 1

        replay = post_v2(http, body, raw=raw)
        assert replay.status_code == 200
        assert replay.json()["inserted_at"] == first.json()["inserted_at"]
        assert len(hornet.calls) == 1

        changed = json.dumps(anchor(dict(MESSAGE, temperature=22)))
        conflict = post_v2(http, body, raw=changed)
        assert conflict.status_code == 409
        assert "different bytes" in conflict.json()["detail"]
        assert len(hornet.calls) == 1

        another_key = post_v2(http, body, key="idem-key-002", raw=raw)
        assert another_key.status_code == 200
        assert len(hornet.calls) == 1


def test_v2_requires_a_well_formed_idempotency_key(client):
    http, hornet = client
    assert post_v2(http, anchor(), key="short").status_code == 400
    assert post_v2(http, anchor(), key="has spaces").status_code == 400
    assert hornet.calls == []


def test_demo_mutations_are_opt_in(tmp_path):
    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
        )
    ) as http:
        assert http.post("/ingest", json=anchor()).status_code == 201
        assert http.post(f"/messages/{BLOCK_ID}/tamper", json={}).status_code == 403
        assert http.post(f"/messages/{BLOCK_ID}/restore").status_code == 403
        assert http.get("/health").json()["demo_mutations"] is False


def test_production_requires_a_token_and_disables_demo_routes(tmp_path):
    with pytest.raises(ValueError, match="LEDGER_API_TOKEN"):
        create_app(
            database_path=str(tmp_path / "missing-token.db"),
            mode="production",
        )
    with pytest.raises(ValueError, match="demo mutations"):
        create_app(
            database_path=str(tmp_path / "unsafe.db"),
            mode="production",
            api_token="test-token",
            demo_mutations=True,
        )

    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
            embedded=True,
            mode="production",
            api_token="test-token",
        )
    ) as http:
        assert post_v2(http, anchor()).status_code == 401
        assert (
            post_v2(
                http,
                anchor(),
                raw=json.dumps(anchor()),
            ).status_code
            == 401
        )
        denied = http.post(
            "/v2/ingest",
            json=anchor(),
            headers={
                "Idempotency-Key": "idem-key-001",
                "Authorization": "Bearer wrong",
            },
        )
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"

        legacy = http.post(
            "/ingest",
            json=anchor(),
            headers={"Authorization": "Bearer test-token"},
        )
        assert legacy.status_code == 403

        accepted = http.post(
            "/v2/ingest",
            json=anchor(),
            headers={
                "Idempotency-Key": "idem-key-001",
                "Authorization": "Bearer test-token",
            },
        )
        assert accepted.status_code == 201
        assert http.get("/health").json()["api_token_required"] is True
        assert http.post(f"/messages/{BLOCK_ID}/tamper", json={}).status_code == 403


def test_paid_context_requires_a_token_and_has_a_quota(tmp_path):
    class Context:
        def __init__(self):
            self.calls = 0

        def search(self, **kwargs):
            self.calls += 1
            return {"provider": "fake", "query": kwargs["species"], "results": []}

        def close(self):
            pass

    web = Context()
    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            context=web,
            mode="production",
            api_token="test-token",
            context_rate_limit=1,
        )
    ) as http:
        body = {"species": "European robin"}
        assert http.post("/context", json=body).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        assert http.post("/context", json=body, headers=headers).status_code == 200
        limited = http.post("/context", json=body, headers=headers)
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
        assert web.calls == 1


def test_public_demo_writes_are_rate_limited(tmp_path):
    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
            ingest_rate_limit=1,
        )
    ) as http:
        assert http.post("/ingest", json=anchor()).status_code == 201
        limited = http.post("/ingest", json=anchor(block_id="0xdef456"))
        assert limited.status_code == 429
        assert limited.headers["retry-after"]


def test_request_body_limit_is_enforced(tmp_path):
    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
            max_body_bytes=128,
        )
    ) as http:
        response = http.post(
            "/v2/ingest",
            content=json.dumps(anchor({"large": "x" * 1000})),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "idem-key-001",
            },
        )
        assert response.status_code == 413


def test_streamed_body_without_content_length_is_still_limited(tmp_path):
    def chunks():
        yield b'{"blockId":"'
        yield b"x" * 256
        yield b'"}'

    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
            max_body_bytes=128,
        )
    ) as http:
        response = http.post(
            "/v2/ingest",
            content=chunks(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "idem-key-001",
            },
        )
        assert response.status_code == 413


def test_valid_streamed_body_is_replayed_to_the_route(tmp_path):
    def chunks():
        raw = json.dumps(anchor()).encode()
        yield raw[:17]
        yield raw[17:]

    with TestClient(
        create_app(
            database_path=str(tmp_path / "ledger.db"),
            hornet=FakeHornet(),
            max_body_bytes=4096,
        )
    ) as http:
        response = http.post(
            "/v2/ingest",
            content=chunks(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "idem-key-001",
            },
        )
        assert response.status_code == 201
        assert response.json()["block_id"] == BLOCK_ID


class BlockingHornet(FakeHornet):
    def __init__(self):
        super().__init__()
        self.armed = False
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch(self, block_id):
        if self.armed:
            self.started.set()
            if not self.release.wait(5):
                raise TimeoutError("test did not release verification")
        return super().fetch(block_id)


def test_tamper_during_verification_cannot_receive_the_stale_verdict(tmp_path):
    hornet = BlockingHornet()
    app = create_app(
        database_path=str(tmp_path / "ledger.db"),
        hornet=hornet,
        demo_mutations=True,
    )
    with TestClient(app) as http:
        http.post("/ingest", json=anchor())
        before = app.state.db.get(BLOCK_ID)
        hornet.armed = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(http.post, f"/messages/{BLOCK_ID}/reverify")
            assert hornet.started.wait(5)
            try:
                assert app.state.db.update_payload(
                    BLOCK_ID,
                    dict(MESSAGE, temperature=123),
                    expected_version=before["version"],
                )
            finally:
                hornet.release.set()
            assert pending.result(timeout=5).status_code == 409

        current = app.state.db.get(BLOCK_ID)
        assert current["version"] == before["version"] + 1
        assert current["status"] == "PENDING"
        assert current["content_match"] is None
        attempts = app.state.db.verification_attempts(BLOCK_ID)
        stale = next(row for row in attempts if row["applied"] == 0)
        assert stale["version"] == before["version"]
        assert json.loads(stale["payload_json"]) == MESSAGE


class BarrierHornet(FakeHornet):
    def __init__(self):
        super().__init__()
        self.armed = False
        self.barrier = threading.Barrier(2)

    def fetch(self, block_id):
        if self.armed:
            self.barrier.wait(timeout=5)
        return super().fetch(block_id)


def test_concurrent_verification_is_compare_and_swap(tmp_path):
    hornet = BarrierHornet()
    app = create_app(
        database_path=str(tmp_path / "ledger.db"),
        hornet=hornet,
    )
    with TestClient(app) as http:
        http.post("/ingest", json=anchor())
        db = app.state.db
        hornet.armed = True

        def verify():
            try:
                return verify_stored(db, hornet, BLOCK_ID)
            except VerificationConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: verify(), range(2)))
        assert sum(result is not None for result in results) == 1
        attempts = db.verification_attempts(BLOCK_ID)
        assert sum(row["applied"] for row in attempts) == 2
        assert any(row["applied"] == 0 for row in attempts)


def test_submissions_and_verification_attempts_are_append_only(client):
    http, _hornet = client
    http.post("/ingest", json=anchor())
    db = http.app.state.db
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.session() as conn:
            conn.execute("UPDATE submissions SET tag = 'changed'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.session() as conn:
            conn.execute("DELETE FROM verification_attempts")


def test_existing_ledger_schema_is_migrated_additively(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE messages (
                block_id_norm TEXT PRIMARY KEY,
                block_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                flow_id TEXT,
                payload_json TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                solid INTEGER,
                content_match INTEGER,
                milestone_index INTEGER,
                raw_block TEXT,
                ledger_payload_json TEXT,
                ledger_tag TEXT,
                status TEXT NOT NULL,
                verified_at TEXT,
                hornet_status INTEGER,
                detail TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO messages (
                block_id_norm, block_id, tag, flow_id, payload_json,
                inserted_at, status, hornet_status, detail, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, 'old', ?)
            """,
            (
                "abc123",
                BLOCK_ID,
                TAG,
                "flow-1",
                json.dumps(MESSAGE),
                "2026-01-01T00:00:00.000000Z",
                201,
                "2026-01-01T00:00:00.000000Z",
            ),
        )

    db = Database(str(path))
    row = db.get(BLOCK_ID)
    assert row["version"] == 1
    assert json.loads(row["submission_payload_json"]) == MESSAGE
    assert json.loads(row["payload_json"]) == MESSAGE
