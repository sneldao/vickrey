from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

import pytest
from app.adapters import (
    DeterministicTestnetSimulator,
    RemoteEvidenceInput,
    RemoteEvidenceResult,
)
from app.signing import dump_json, iso_utc, verdict_signing_bytes
from fastapi.testclient import TestClient

from tests.support import (
    StaticRemoteAdapter,
    challenge_payload,
    create_challenge,
    create_task,
    headers,
    record_verdict,
    run_remote,
    sealed_flow,
    settle,
    submission_payload,
    verdict_body,
)


@pytest.mark.parametrize(
    "location",
    [
        "51.5074, -0.1278",
        "latitude 51.5074, longitude -0.1278",
        "51°30'26.6\"N 0°07'39.6\"W",
        "51.5074 N, 0.1278 W",
        "51.5074 -0.1278",
    ],
)
def test_precise_coordinates_are_rejected_from_public_criteria(client, clock, location):
    payload = challenge_payload(clock)
    payload["criteria"]["public_location"] = location
    response = client.post(
        "/v1/challenges",
        headers=headers("claimant", f"coordinate-{abs(hash(location))}"),
        json=payload,
    )
    assert response.status_code == 422
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        assert conn.execute("SELECT count(*) FROM challenges").fetchone()[0] == 0


def test_raw_observation_summary_is_not_accepted_or_persisted(client, clock):
    created = create_challenge(client, clock, key="privacy-create")
    challenge_id = created.json()["challenge"]["id"]
    assert run_remote(client, challenge_id, key="privacy-remote").status_code == 201
    assert create_task(client, challenge_id, key="privacy-task").status_code == 201
    marker = "PRIVATE-SUMMARY-MARKER exact OCR text from the notice"
    response = client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers=headers("observer", "privacy-submit"),
        json={
            "commitment": "a" * 64,
            "public_metadata": {
                "captured_at": iso_utc(clock()),
                "public_location": "North trail public kiosk",
                "public_summary": marker,
            },
        },
    )
    assert response.status_code == 422
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        assert conn.execute("SELECT count(*) FROM submissions").fetchone()[0] == 0


def test_submission_persists_only_controlled_public_metadata(client, clock):
    created = create_challenge(client, clock, key="status-create")
    challenge_id = created.json()["challenge"]["id"]
    assert run_remote(client, challenge_id, key="status-remote").status_code == 201
    assert create_task(client, challenge_id, key="status-task").status_code == 201
    response = client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers=headers("observer", "status-submit"),
        json={
            "commitment": "a" * 64,
            "public_metadata": {
                "captured_at": iso_utc(clock()),
                "public_location": "North trail public kiosk",
                "observation_status": "observed",
            },
        },
    )
    assert response.status_code == 201, response.text
    metadata = response.json()["submission"]["public_metadata"]
    assert set(metadata) == {"captured_at", "public_location", "observation_status"}
    submission_id = response.json()["submission"]["id"]
    authorized = client.get(
        f"/v1/submissions/{submission_id}",
        headers=headers("observer", "status-read"),
    )
    assert authorized.json()["public_metadata"] == metadata
    with sqlite3.connect(client.app.state.service.db.path) as conn:
        stored = conn.execute(
            "SELECT public_metadata_json FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()[0]
    assert "public_summary" not in stored
    assert stored == dump_json(metadata)


def test_exact_replay_succeeds_after_principal_quota_is_exhausted(
    make_app, settings, clock
):
    config = replace(settings, quota_per_hour=1)
    app = make_app(config=config)
    with TestClient(app) as client:
        first = create_challenge(client, clock, key="quota-replay")
        assert first.status_code == 201
        replay = create_challenge(client, clock, key="quota-replay")
        assert replay.status_code == 201
        assert replay.json() == first.json()
        assert replay.headers["idempotency-replayed"] == "true"


def test_quota_is_shared_across_operations_for_one_principal(make_app, settings, clock):
    config = replace(settings, quota_per_hour=1)
    app = make_app(config=config)
    with TestClient(app) as client:
        created = create_challenge(client, clock, key="shared-quota-create")
        assert created.status_code == 201
        challenge_id = created.json()["challenge"]["id"]
        remote = run_remote(client, challenge_id, key="shared-quota-remote")
        assert remote.status_code == 429
        assert int(remote.headers["retry-after"]) > 0


class PausingRemoteAdapter(StaticRemoteAdapter):
    def __init__(self) -> None:
        super().__init__("insufficient")
        self.started = threading.Event()
        self.release = threading.Event()

    def evaluate(self, _evidence_input: RemoteEvidenceInput) -> RemoteEvidenceResult:
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=2)
        return RemoteEvidenceResult(
            status="insufficient",
            summary="Paused test context; not proof.",
            provider=self.provider,
            provider_version=self.provider_version,
            source_label="test_paused_context",
        )


def test_concurrent_identical_remote_requests_call_adapter_once(make_app, clock):
    adapter = PausingRemoteAdapter()
    app = make_app(remote=adapter)
    service = app.state.service
    original_replay = service.db.replay
    second_replay = threading.Event()
    replay_lock = threading.Lock()
    replay_calls = 0

    def observed_replay(*args, **kwargs):
        nonlocal replay_calls
        result = original_replay(*args, **kwargs)
        if kwargs.get("operation") == "remote_evidence":
            with replay_lock:
                replay_calls += 1
                if replay_calls >= 2:
                    second_replay.set()
        return result

    service.db.replay = observed_replay
    with TestClient(app) as client:
        created = create_challenge(client, clock, key="remote-race-create")
        challenge_id = created.json()["challenge"]["id"]
        barrier = threading.Barrier(2)

        def call():
            with TestClient(app) as thread_client:
                barrier.wait(timeout=5)
                return run_remote(thread_client, challenge_id, key="remote-race-key")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call) for _ in range(2)]
            try:
                assert adapter.started.wait(timeout=5)
                second_replay.wait(timeout=0.5)
            finally:
                adapter.release.set()
            responses = [future.result(timeout=15) for future in futures]
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert adapter.calls == 1
    assert (
        sum(
            response.headers["idempotency-replayed"] == "true" for response in responses
        )
        == 1
    )


def test_capture_before_field_task_authorization_is_rejected(client, clock):
    created = create_challenge(client, clock, key="capture-create")
    challenge_id = created.json()["challenge"]["id"]
    assert run_remote(client, challenge_id, key="capture-remote").status_code == 201
    clock.advance(hours=1)
    assert create_task(client, challenge_id, key="capture-task").status_code == 201
    response = client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers=headers("observer", "capture-submit"),
        json={
            "commitment": "a" * 64,
            "public_metadata": {
                "captured_at": iso_utc(clock() - timedelta(minutes=30)),
                "public_location": "North trail public kiosk",
                "observation_status": "observed",
            },
        },
    )
    assert response.status_code == 422
    assert "field-task" in response.json()["detail"]


def gate_transactions(monkeypatch, service):
    entered = threading.Event()
    release = threading.Event()
    original_transaction = service.db.transaction

    @contextmanager
    def gated_transaction():
        entered.set()
        if not release.wait(timeout=5):
            raise RuntimeError("transaction gate was not released")
        with original_transaction() as conn:
            yield conn

    monkeypatch.setattr(service.db, "transaction", gated_transaction)
    monkeypatch.setattr(service, "_quota", lambda *args, **kwargs: None)
    return entered, release


def test_field_task_expiry_is_checked_after_write_lock(make_app, clock, monkeypatch):
    app = make_app(remote=StaticRemoteAdapter("insufficient"))
    service = app.state.service
    with TestClient(app) as client:
        created = create_challenge(client, clock, key="expiry-task-create")
        challenge_id = created.json()["challenge"]["id"]
        assert (
            run_remote(client, challenge_id, key="expiry-task-remote").status_code
            == 201
        )
        entered, release = gate_transactions(monkeypatch, service)

        def call():
            with TestClient(app) as thread_client:
                return create_task(thread_client, challenge_id, key="expiry-task-key")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call)
            try:
                assert entered.wait(timeout=5)
                clock.advance(hours=3)
            finally:
                release.set()
            response = future.result(timeout=15)
    assert response.status_code == 410


def test_submission_expiry_is_checked_after_write_lock(make_app, clock, monkeypatch):
    app = make_app(remote=StaticRemoteAdapter("insufficient"))
    service = app.state.service
    with TestClient(app) as client:
        created = create_challenge(client, clock, key="expiry-submit-create")
        challenge_id = created.json()["challenge"]["id"]
        assert (
            run_remote(client, challenge_id, key="expiry-submit-remote").status_code
            == 201
        )
        assert (
            create_task(client, challenge_id, key="expiry-submit-task").status_code
            == 201
        )
        body = submission_payload(clock, "a" * 64)
        entered, release = gate_transactions(monkeypatch, service)

        def call():
            with TestClient(app) as thread_client:
                return thread_client.post(
                    f"/v1/challenges/{challenge_id}/submissions",
                    headers=headers("observer", "expiry-submit-key"),
                    json=body,
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call)
            try:
                assert entered.wait(timeout=5)
                clock.advance(hours=3)
            finally:
                release.set()
            response = future.result(timeout=15)
    assert response.status_code == 410


class MismatchedSettlementAdapter:
    name = "mismatched_testnet_simulator"

    def __init__(self, mismatch: str) -> None:
        self.mismatch = mismatch
        self.delegate = DeterministicTestnetSimulator()

    def settle(self, request):
        result = self.delegate.settle(request)
        if self.mismatch == "status":
            return replace(result, status="no_payout")
        return replace(result, currency="WRONG_CURRENCY")


@pytest.mark.parametrize("mismatch", ["status", "currency"])
def test_settlement_adapter_must_match_operation_and_currency(
    make_app, clock, private_key, mismatch
):
    app = make_app(
        remote=StaticRemoteAdapter("insufficient"),
        settlement=MismatchedSettlementAdapter(mismatch),
    )
    with TestClient(app) as client:
        flow = sealed_flow(client, clock)
        challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
        submission = client.get(
            f"/v1/submissions/{flow['submission_id']}",
            headers=headers("observer", "settlement-mismatch-read"),
        ).json()
        resolved = record_verdict(
            client, private_key, clock, flow, challenge, submission
        )
        assert resolved.status_code == 201
        response = settle(client, resolved.json()["verdict"]["id"])
        assert response.status_code == 502
        with sqlite3.connect(app.state.service.db.path) as conn:
            assert conn.execute("SELECT count(*) FROM settlements").fetchone()[0] == 0


def test_verdict_signature_and_request_use_the_same_reason_normalization(
    client, clock, private_key
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "reason-read"),
    ).json()
    body = verdict_body(private_key, clock, flow, challenge, submission)
    body["reason"] = f"  {body['reason']}  "
    signing_payload = {**body, "issued_at": clock()}
    body["signature"] = private_key.sign(verdict_signing_bytes(signing_payload)).hex()
    response = client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", "reason-verdict"),
        json=body,
    )
    assert response.status_code == 201, response.text
    assert response.json()["verdict"]["reason"] == body["reason"].strip()


@pytest.mark.parametrize("with_remote", [False, True])
def test_expired_challenge_never_reports_an_actionable_state(
    client, clock, with_remote
):
    created = create_challenge(client, clock, key=f"expired-state-{with_remote}")
    challenge_id = created.json()["challenge"]["id"]
    if with_remote:
        assert (
            run_remote(client, challenge_id, key="expired-state-remote").status_code
            == 201
        )
    clock.advance(hours=3)
    response = client.get(f"/v1/challenges/{challenge_id}")
    assert response.status_code == 200
    assert response.json()["state"] == "expired"
