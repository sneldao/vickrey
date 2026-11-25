from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest
from app.config import Settings
from fastapi.testclient import TestClient

from tests.support import (
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


def test_bearer_roles_are_enforced_and_client_roles_are_not_trusted(client, clock):
    missing = client.post("/v1/challenges", json=challenge_payload(clock))
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    invalid = client.post(
        "/v1/challenges",
        headers={
            "Authorization": "Bearer not-a-configured-token",
            "Idempotency-Key": "bad-token-1",
        },
        json=challenge_payload(clock),
    )
    assert invalid.status_code == 401
    wrong_role = client.post(
        "/v1/challenges",
        headers=headers("observer", "wrong-role-1"),
        json=challenge_payload(clock),
    )
    assert wrong_role.status_code == 403
    spoofed = challenge_payload(clock)
    spoofed["role"] = "claimant"
    spoofed["sponsor"] = "someone-else"
    spoof = client.post(
        "/v1/challenges", headers=headers("claimant", "spoof-role-1"), json=spoofed
    )
    assert spoof.status_code == 422


def test_each_workflow_mutation_requires_its_configured_role(
    client, clock, private_key
):
    created = create_challenge(client, clock)
    challenge_id = created.json()["challenge"]["id"]
    remote_wrong = client.post(
        f"/v1/challenges/{challenge_id}/remote-evidence",
        headers=headers("observer", "remote-wrong"),
    )
    assert remote_wrong.status_code == 403
    assert run_remote(client, challenge_id).status_code == 201
    task_wrong = client.post(
        f"/v1/challenges/{challenge_id}/field-task",
        headers=headers("observer", "task-wrong-1"),
    )
    assert task_wrong.status_code == 403
    assert create_task(client, challenge_id).status_code == 201
    submission_wrong = client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers=headers("claimant", "submit-wrong"),
        json={
            "commitment": "a" * 64,
            "public_metadata": {
                "captured_at": "2026-11-24T12:00:00.000000Z",
                "public_location": "North trail public kiosk",
                "observation_status": "observed",
            },
        },
    )
    assert submission_wrong.status_code == 403
    submitted = submit_evidence(client, clock, challenge_id)
    assert submitted.status_code == 201
    flow = {
        "challenge_id": challenge_id,
        "submission_id": submitted.json()["submission"]["id"],
    }
    challenge = client.get(f"/v1/challenges/{challenge_id}").json()
    submission = submitted.json()["submission"]
    wrong_verifier = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("observer", "verdict-wrong"),
        json=verdict_body(private_key, clock, flow, challenge, submission),
    )
    assert wrong_verifier.status_code == 403
    resolved = record_verdict(client, private_key, clock, flow, challenge, submission)
    assert resolved.status_code == 201
    wrong_settlement = client.post(
        f"/v1/verdicts/{resolved.json()['verdict']['id']}/settlement",
        headers=headers("verifier", "settle-wrong"),
    )
    assert wrong_settlement.status_code == 403
    assert settle(client, resolved.json()["verdict"]["id"]).status_code == 201


def test_observer_identity_and_raw_location_fields_cannot_be_supplied(client, clock):
    flow = sealed_flow(client, clock)
    body = {
        "commitment": "b" * 64,
        "observer": "observer-2",
        "public_metadata": {
            "captured_at": "2026-11-24T12:00:00.000000Z",
            "public_location": "North trail public kiosk",
            "observation_status": "observed",
            "latitude": 51.5,
            "longitude": -0.1,
        },
    }
    response = client.post(
        f"/v1/challenges/{flow['challenge_id']}/submissions",
        headers=headers("observer", "spoof-observer"),
        json=body,
    )
    assert response.status_code == 422


def test_tampered_or_stale_verdicts_are_audited_without_resolution(
    client, clock, private_key, make_app
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-tamper"),
    ).json()
    valid = verdict_body(private_key, clock, flow, challenge, submission)
    valid["reason"] = "Changed after signing."
    tampered = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", "verdict-tamper"),
        json=valid,
    )
    assert tampered.status_code == 422
    assert tampered.json()["code"] == "invalid_verifier_signature"

    stale = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        submission_version=2,
        key_number=2,
    )
    stale_response = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", "verdict-stale-1"),
        json=stale,
    )
    assert stale_response.status_code == 409

    rebound = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        commitment="f" * 64,
        key_number=3,
    )
    rebound_response = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", "verdict-rebind-1"),
        json=rebound,
    )
    assert rebound_response.status_code == 409

    old = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        issued_at=clock() - timedelta(hours=2),
        key_number=4,
    )
    old_response = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", "verdict-old-001"),
        json=old,
    )
    assert old_response.status_code == 422

    app = make_app()
    with sqlite3.connect(app.state.service.db.path) as conn:
        outcomes = [
            row[0]
            for row in conn.execute(
                "SELECT outcome FROM verification_attempts ORDER BY attempt_id"
            )
        ]
        count = conn.execute("SELECT count(*) FROM verdicts").fetchone()[0]
    assert outcomes == [
        "invalid_signature",
        "stale_version",
        "binding_mismatch",
        "invalid_timestamp",
    ]
    assert count == 0


def test_request_size_limit_rejects_declared_and_chunked_bodies(
    make_app, settings, clock
):
    config = replace(settings, max_request_bytes=1_024)
    app = make_app(config=config)
    with TestClient(app) as client:
        oversized = challenge_payload(clock, claim="x" * 2_000)
        response = client.post(
            "/v1/challenges",
            headers=headers("claimant", "large-body-1"),
            json=oversized,
        )
        assert response.status_code == 413

        def chunks():
            yield b" " * 512
            yield b" " * 512
            yield b" " * 512

        chunked = client.post(
            "/v1/challenges",
            headers={
                **headers("claimant", "chunked-body"),
                "Content-Type": "application/json",
            },
            content=chunks(),
        )
        assert chunked.status_code == 413


def test_hourly_quota_is_durable_and_returns_retry_after(make_app, settings, clock):
    config = replace(settings, quota_per_hour=1)
    app = make_app(config=config)
    with TestClient(app) as client:
        first = create_challenge(client, clock, key="quota-first")
        assert first.status_code == 201
        second = create_challenge(client, clock, key="quota-second")
        assert second.status_code == 429
        assert int(second.headers["retry-after"]) > 0
        assert client.get("/healthz").status_code == 200
        clock.advance(hours=1)
        third = create_challenge(client, clock, key="quota-third")
        assert third.status_code == 201


def test_production_requires_all_tokens_and_ed25519_key(tmp_path, private_key):
    from cryptography.hazmat.primitives import serialization

    public = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    with pytest.raises(ValueError, match="requires RECEIPTS_TOKENS_JSON"):
        Settings.from_env(
            {
                "RECEIPTS_MODE": "production",
                "RECEIPTS_DATABASE_PATH": str(tmp_path / "prod.db"),
                "RECEIPTS_VERIFIER_PUBLIC_KEY": public,
            }
        )
    tokens = {
        "claimant-token-0000000000000000000001": {"role": "claimant", "subject": "c1"},
        "observer-token-0000000000000000000002": {"role": "observer", "subject": "o1"},
        "verifier-token-0000000000000000000003": {"role": "verifier", "subject": "v1"},
        "settlement-token-000000000000000000004": {
            "role": "settlement",
            "subject": "s1",
        },
    }
    import json

    env = {
        "RECEIPTS_MODE": "production",
        "RECEIPTS_DATABASE_PATH": str(tmp_path / "prod.db"),
        "RECEIPTS_TOKENS_JSON": json.dumps(tokens),
        "RECEIPTS_VERIFIER_PUBLIC_KEY": public,
    }
    config = Settings.from_env(env)
    assert config.mode == "production"
    assert len(config.tokens) == 4
    env["RECEIPTS_TOKENS_JSON"] = json.dumps(
        {key: value for key, value in tokens.items() if value["role"] != "settlement"}
    )
    with pytest.raises(ValueError, match="settlement"):
        Settings.from_env(env)


def test_demo_defaults_require_explicit_demo_mode(tmp_path, private_key):
    import json

    tokens = {
        "claimant-token-0000000000000000000001": {"role": "claimant", "subject": "c1"},
        "observer-token-0000000000000000000002": {"role": "observer", "subject": "o1"},
        "verifier-token-0000000000000000000003": {"role": "verifier", "subject": "v1"},
        "settlement-token-000000000000000000004": {
            "role": "settlement",
            "subject": "s1",
        },
    }
    env = {
        "RECEIPTS_DATABASE_PATH": str(tmp_path / "prod.db"),
        "RECEIPTS_TOKENS_JSON": json.dumps(tokens),
    }
    with pytest.raises(ValueError, match="PUBLIC_KEY"):
        Settings.from_env(env)
    demo = Settings.from_env(
        {"RECEIPTS_MODE": "demo", "RECEIPTS_DATABASE_PATH": str(tmp_path / "d.db")}
    )
    assert demo.tokens["demo-claimant-token-change-me"].role == "claimant"
