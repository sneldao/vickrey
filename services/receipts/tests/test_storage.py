from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.db import SCHEMA_V1, Database
from tests.support import (
    CountingSettlementAdapter,
    StaticRemoteAdapter,
    challenge_payload,
    create_challenge,
    create_task,
    headers,
    record_verdict,
    run_remote,
    sealed_flow,
    settle,
    submit_evidence,
    verdict_body,
)


def test_all_mutations_replay_exactly_without_duplicate_side_effects(
    client, clock, private_key, remote_adapter, settlement_adapter
):
    first_create = create_challenge(client, clock, key="replay-create")
    assert first_create.status_code == 201
    challenge_id = first_create.json()["challenge"]["id"]
    first_remote = run_remote(client, challenge_id, key="replay-remote")
    first_task = create_task(client, challenge_id, key="replay-task-001")
    first_submit = submit_evidence(client, clock, challenge_id, key="replay-submit")
    assert (
        first_remote.status_code
        == first_task.status_code
        == first_submit.status_code
        == 201
    )
    flow = {
        "challenge_id": challenge_id,
        "submission_id": first_submit.json()["submission"]["id"],
    }
    challenge = client.get(f"/v1/challenges/{challenge_id}").json()
    submission = first_submit.json()["submission"]
    first_verdict = record_verdict(
        client, private_key, clock, flow, challenge, submission, key="replay-verdict"
    )
    assert first_verdict.status_code == 201
    first_settle = settle(
        client, first_verdict.json()["verdict"]["id"], key="replay-settle"
    )
    assert first_settle.status_code == 201

    replays = [
        create_challenge(client, clock, key="replay-create"),
        run_remote(client, challenge_id, key="replay-remote"),
        create_task(client, challenge_id, key="replay-task-001"),
        submit_evidence(client, clock, challenge_id, key="replay-submit"),
        record_verdict(
            client,
            private_key,
            clock,
            flow,
            challenge,
            submission,
            key="replay-verdict",
        ),
        settle(client, first_verdict.json()["verdict"]["id"], key="replay-settle"),
    ]
    originals = [
        first_create,
        first_remote,
        first_task,
        first_submit,
        first_verdict,
        first_settle,
    ]
    for original, replay in zip(originals, replays, strict=True):
        assert replay.status_code == original.status_code
        assert replay.json() == original.json()
        assert replay.headers["idempotency-replayed"] == "true"
    assert remote_adapter.calls == 1
    assert len(settlement_adapter.calls) == 1

    with sqlite3.connect(client.app.state.service.db.path) as conn:
        for table in (
            "challenges",
            "remote_evidence",
            "field_tasks",
            "submissions",
            "verdicts",
            "settlements",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1


def test_conflicting_idempotency_and_duplicate_active_submission_are_refused(
    client, clock
):
    first = create_challenge(client, clock, key="conflict-create")
    assert first.status_code == 201
    changed = create_challenge(client, clock, key="conflict-create", bounty_amount=251)
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"
    reformatted = client.post(
        "/v1/challenges",
        headers={
            **headers("claimant", "conflict-create"),
            "Content-Type": "application/json",
        },
        content=json.dumps(challenge_payload(clock), indent=2),
    )
    assert reformatted.status_code == 409
    assert reformatted.json()["code"] == "idempotency_conflict"
    challenge_id = first.json()["challenge"]["id"]
    assert run_remote(client, challenge_id, key="conflict-remote").status_code == 201
    assert create_task(client, challenge_id, key="conflict-task00").status_code == 201
    submitted = submit_evidence(client, clock, challenge_id, key="conflict-submit")
    assert submitted.status_code == 201
    changed_submit = submit_evidence(
        client, clock, challenge_id, commitment="b" * 64, key="conflict-submit"
    )
    assert changed_submit.status_code == 409
    assert changed_submit.json()["code"] == "idempotency_conflict"
    duplicate = submit_evidence(
        client, clock, challenge_id, "c" * 64, key="another-submit"
    )
    assert duplicate.status_code == 409


def test_immutable_triggers_block_update_and_delete(client, clock, private_key):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "immutable-read"),
    ).json()
    resolved = record_verdict(client, private_key, clock, flow, challenge, submission)
    assert resolved.status_code == 201
    assert settle(client, resolved.json()["verdict"]["id"]).status_code == 201

    with sqlite3.connect(client.app.state.service.db.path) as conn:
        for table in ("challenges", "submissions", "verdicts", "settlements"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f"UPDATE {table} SET rowid = rowid")
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f"DELETE FROM {table}")
        state = conn.execute(
            "SELECT status, version FROM submission_states WHERE submission_id = ?",
            (flow["submission_id"],),
        ).fetchone()
        assert state == ("resolved", 2)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE verification_attempts SET outcome = 'applied'")


def test_concurrent_conflicting_resolutions_apply_exactly_once(
    client, clock, private_key
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "concurrent-read"),
    ).json()
    accepted = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        decision="accepted",
        key_number=10,
    )
    rejected = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        decision="rejected",
        key_number=11,
    )
    barrier = threading.Barrier(2)

    def call(body, key):
        with TestClient(client.app) as thread_client:
            barrier.wait(timeout=5)
            return thread_client.post(
                f"/v1/submissions/{flow['submission_id']}/verdicts",
                headers=headers("verifier", key),
                json=body,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(call, accepted, "race-verdict-a"),
            pool.submit(call, rejected, "race-verdict-b"),
        ]
        responses = [future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    winner = next(response for response in responses if response.status_code == 201)
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        assert conn.execute("SELECT count(*) FROM verdicts").fetchone()[0] == 1
        attempts = conn.execute(
            "SELECT outcome FROM verification_attempts ORDER BY attempt_id"
        ).fetchall()
        assert [row[0] for row in attempts] == ["applied", "already_resolved"]
    paid = settle(client, winner.json()["verdict"]["id"])
    assert paid.status_code == 201
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        assert conn.execute("SELECT count(*) FROM settlements").fetchone()[0] == 1


def test_concurrent_identical_idempotent_resolution_replays_one_resource(
    client, clock, private_key
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "same-race-read"),
    ).json()
    body = verdict_body(private_key, clock, flow, challenge, submission, key_number=20)
    barrier = threading.Barrier(2)

    def call():
        with TestClient(client.app) as thread_client:
            barrier.wait(timeout=5)
            return thread_client.post(
                f"/v1/submissions/{flow['submission_id']}/verdicts",
                headers=headers("verifier", "same-race-key"),
                json=body,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        assert conn.execute("SELECT count(*) FROM verdicts").fetchone()[0] == 1
        assert (
            conn.execute("SELECT count(*) FROM verification_attempts").fetchone()[0]
            == 1
        )


def test_restart_persistence_and_idempotent_settlement_replay(
    make_app, settings, clock, private_key
):
    remote_one = StaticRemoteAdapter("insufficient")
    settlement_one = CountingSettlementAdapter()
    app_one = make_app(remote=remote_one, settlement=settlement_one)
    with TestClient(app_one) as client:
        flow = sealed_flow(client, clock)
        challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
        submission = client.get(
            f"/v1/submissions/{flow['submission_id']}",
            headers=headers("observer", "restart-read"),
        ).json()
        resolved = record_verdict(
            client, private_key, clock, flow, challenge, submission
        )
        assert resolved.status_code == 201
        verdict_id = resolved.json()["verdict"]["id"]
        paid = settle(client, verdict_id, key="restart-settle")
        assert paid.status_code == 201
        receipt_before = client.get(f"/v1/receipts/{flow['challenge_id']}").json()

    remote_two = StaticRemoteAdapter("insufficient")
    settlement_two = CountingSettlementAdapter()
    app_two = make_app(remote=remote_two, settlement=settlement_two)
    with TestClient(app_two) as client:
        receipt_after = client.get(f"/v1/receipts/{flow['challenge_id']}")
        assert receipt_after.status_code == 200
        assert receipt_after.json() == receipt_before
        replay = settle(client, verdict_id, key="restart-settle")
        assert replay.status_code == 201
        assert replay.json() == paid.json()
        assert replay.headers["idempotency-replayed"] == "true"
        assert settlement_two.calls == []
        assert (
            client.get(f"/v1/challenges/{flow['challenge_id']}").json()["state"]
            == "resolved"
        )


def test_schema_is_additive_and_future_versions_fail_closed(settings):
    database = Database(settings.database_path)
    with database.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    Database(settings.database_path)
    with database.connect() as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="newer"):
        Database(settings.database_path)


def test_principal_quota_migration_preserves_latest_window_totals(settings):
    with sqlite3.connect(settings.database_path) as conn:
        conn.executescript(SCHEMA_V1)
        conn.executemany(
            "INSERT INTO request_usage (subject, operation, window_start, count) "
            "VALUES (?, ?, ?, ?)",
            [
                ("alice", "create_challenge", 100, 2),
                ("alice", "remote_evidence", 100, 3),
                ("alice", "settlement", 50, 40),
                ("bob", "create_challenge", 200, 1),
            ],
        )
        conn.execute("PRAGMA user_version=1")

    Database(settings.database_path)
    with Database(settings.database_path).connect() as conn:
        rows = conn.execute(
            "SELECT subject, window_start, count FROM principal_request_usage "
            "ORDER BY subject"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("alice", 100, 5),
            ("bob", 200, 1),
        ]
