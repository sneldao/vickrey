from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters import (
    DeterministicTestnetSimulator,
    RemoteEvidenceInput,
    RemoteEvidenceResult,
    SettlementRequest,
    SettlementResult,
)
from app.models import VerdictIn
from app.signing import iso_utc, verdict_signing_bytes

DEMO_TOKENS = {
    "claimant": "demo-claimant-token-change-me",
    "observer": "demo-observer-token-change-me",
    "verifier": "demo-verifier-token-change-me",
    "settlement": "demo-settlement-token-change-me",
}


def headers(role: str, key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {DEMO_TOKENS[role]}", "Idempotency-Key": key}


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float = 0, hours: float = 0, days: float = 0) -> None:
        self.current += timedelta(seconds=seconds, hours=hours, days=days)


class StaticRemoteAdapter:
    provider = "test_static_remote"
    provider_version = "test-1"

    def __init__(self, status: str = "insufficient") -> None:
        self.status = status
        self.calls = 0

    def evaluate(self, evidence_input: RemoteEvidenceInput) -> RemoteEvidenceResult:
        self.calls += 1
        return RemoteEvidenceResult(
            status=self.status,
            summary="Deterministic test context; not proof.",
            provider=self.provider,
            provider_version=self.provider_version,
            source_label="test_static_context",
        )


class CountingSettlementAdapter:
    name = "counting_testnet_simulator"

    def __init__(self) -> None:
        self.calls: list[SettlementRequest] = []
        self.delegate = DeterministicTestnetSimulator()

    def settle(self, request: SettlementRequest) -> SettlementResult:
        self.calls.append(request)
        return self.delegate.settle(request)


def challenge_payload(clock: FixedClock, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "claim": "The public north-trail kiosk notice is present today.",
        "category": "public_notice",
        "criteria": {
            "must_observe": "Read the posted notice at the public kiosk.",
            "public_location": "North trail public kiosk",
            "radius_m": 25,
            "required_details": ["notice title", "visible posting date"],
            "reject_if": ["notice is absent", "notice is unreadable"],
        },
        "expires_at": iso_utc(clock() + timedelta(hours=2)),
        "bounty_amount": 250,
    }
    payload.update(overrides)
    return payload


def create_challenge(
    client: Any, clock: FixedClock, key: str = "create-0001", **overrides: Any
):
    return client.post(
        "/v1/challenges",
        headers=headers("claimant", key),
        json=challenge_payload(clock, **overrides),
    )


def run_remote(client: Any, challenge_id: str, key: str = "remote-0001"):
    return client.post(
        f"/v1/challenges/{challenge_id}/remote-evidence",
        headers=headers("claimant", key),
    )


def create_task(client: Any, challenge_id: str, key: str = "task-0001"):
    return client.post(
        f"/v1/challenges/{challenge_id}/field-task",
        headers=headers("claimant", key),
    )


def submission_payload(
    clock: FixedClock, commitment: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "commitment": commitment,
        "public_metadata": {
            "captured_at": iso_utc(clock()),
            "public_location": "North trail public kiosk",
            "observation_status": "observed",
        },
    }
    payload.update(overrides)
    return payload


def submit_evidence(
    client: Any,
    clock: FixedClock,
    challenge_id: str,
    commitment: str = "a" * 64,
    key: str = "submit-0001",
    **overrides: Any,
):
    return client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers=headers("observer", key),
        json=submission_payload(clock, commitment, **overrides),
    )


def sealed_flow(
    client: Any, clock: FixedClock, commitment: str = "a" * 64, *, prefix: str = ""
) -> dict[str, str]:
    created = create_challenge(client, clock, key=f"{prefix}create-0001")
    assert created.status_code == 201, created.text
    challenge_id = created.json()["challenge"]["id"]
    remote = run_remote(client, challenge_id, key=f"{prefix}remote-0001")
    assert remote.status_code == 201, remote.text
    task = create_task(client, challenge_id, key=f"{prefix}task-0001")
    assert task.status_code == 201, task.text
    submission = submit_evidence(
        client, clock, challenge_id, commitment, key=f"{prefix}submit-0001"
    )
    assert submission.status_code == 201, submission.text
    return {
        "challenge_id": challenge_id,
        "remote_id": remote.json()["remote_evidence"]["id"],
        "task_id": task.json()["field_task"]["id"],
        "submission_id": submission.json()["submission"]["id"],
    }


def verdict_body(
    private_key: Ed25519PrivateKey,
    clock: FixedClock,
    flow: dict[str, str],
    challenge: dict[str, Any],
    submission: dict[str, Any],
    *,
    decision: str = "accepted",
    key_number: int = 1,
    **overrides: Any,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "verdict_id": f"00000000-0000-4000-8000-{key_number:012d}",
        "challenge_id": flow["challenge_id"],
        "submission_id": flow["submission_id"],
        "submission_version": 1,
        "commitment": submission["commitment"],
        "criteria_hash": challenge["criteria_hash"],
        "verdict": decision,
        "policy_id": "public-notice-v1",
        "policy_version": 1,
        "reason": f"Policy applied: {decision}.",
        "issued_at": clock(),
        "signature": "0" * 128,
    }
    values.update(overrides)
    model = VerdictIn(**values)
    signature = private_key.sign(verdict_signing_bytes(model.model_dump())).hex()
    return {**model.model_dump(mode="json"), "signature": signature}


def record_verdict(
    client: Any,
    private_key: Ed25519PrivateKey,
    clock: FixedClock,
    flow: dict[str, str],
    challenge: dict[str, Any],
    submission: dict[str, Any],
    *,
    decision: str = "accepted",
    key: str = "verdict-0001",
    key_number: int = 1,
    **overrides: Any,
):
    body = verdict_body(
        private_key,
        clock,
        flow,
        challenge,
        submission,
        decision=decision,
        key_number=key_number,
        **overrides,
    )
    return client.post(
        f"/v1/submissions/{flow['submission_id']}/verdicts",
        headers=headers("verifier", key),
        json=body,
    )


def settle(client: Any, verdict_id: str, key: str = "settle-0001"):
    return client.post(
        f"/v1/verdicts/{verdict_id}/settlement",
        headers=headers("settlement", key),
    )
