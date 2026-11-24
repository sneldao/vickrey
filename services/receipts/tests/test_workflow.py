from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.support import (
    StaticRemoteAdapter,
    create_challenge,
    create_task,
    headers,
    record_verdict,
    run_remote,
    sealed_flow,
    settle,
    submit_evidence,
)


def test_complete_accepted_flow_and_redacted_public_receipt(
    client, clock, private_key, settlement_adapter
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0001"),
    ).json()
    assert challenge["criteria_hash"] and len(challenge["criteria_hash"]) == 64
    assert challenge["brief"]["objective"]
    assert challenge["remote_evidence"]["is_cryptographic_proof"] is False
    assert submission["status"] == "open"

    resolved = record_verdict(
        client, private_key, clock, flow, challenge, submission, decision="accepted"
    )
    assert resolved.status_code == 201, resolved.text
    verdict = resolved.json()["verdict"]
    assert verdict["policy"] == {"id": "public-notice-v1", "version": 1}
    assert verdict["verification_source"] == "configured_verifier_policy_decision"

    pending_receipt = client.get(f"/v1/receipts/{flow['challenge_id']}")
    assert pending_receipt.status_code == 200
    assert pending_receipt.json()["status"] == "awaiting_settlement"
    assert pending_receipt.json()["settlement"]["txid"] is None

    paid = settle(client, verdict["id"])
    assert paid.status_code == 201, paid.text
    settlement = paid.json()["settlement"]
    assert settlement["operation"] == "payout"
    assert settlement["recipient"] == "observer-1"
    assert settlement["amount"] == 250
    assert settlement["txid"].startswith("sim_")
    assert settlement["real_funds"] is False
    assert len(settlement_adapter.calls) == 1

    receipt = client.get(f"/v1/receipts/{flow['challenge_id']}")
    assert receipt.status_code == 200
    body = receipt.json()
    assert body["status"] == "complete"
    assert body["criteria_hash"] == challenge["criteria_hash"]
    assert body["field_evidence"]["commitment"] == "a" * 64
    assert body["field_evidence"]["raw_observation_received"] is False
    assert body["verdict"]["verdict"] == "accepted"
    assert body["settlement"]["txid"] == settlement["txid"]
    assert body["timestamps"]["settlement_created_at"] is not None
    assert body["verification_sources"]["remote_evidence"] == "test_static_context"
    assert (
        body["verification_sources"]["field_evidence"]
        == "sealed_record_commitment_only"
    )
    assert "PRIVATE-SUMMARY-MARKER" not in receipt.text
    assert "public_metadata" not in receipt.text
    assert "public_summary" not in receipt.text
    assert "no real funds" in " ".join(body["limitations"])


def test_rejected_flow_refunds_sponsor(client, clock, private_key, settlement_adapter):
    flow = sealed_flow(client, clock, commitment="b" * 64)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0002"),
    ).json()
    resolved = record_verdict(
        client, private_key, clock, flow, challenge, submission, decision="rejected"
    )
    assert resolved.status_code == 201, resolved.text
    paid = settle(client, resolved.json()["verdict"]["id"])
    assert paid.status_code == 201
    settlement = paid.json()["settlement"]
    assert settlement["operation"] == "refund"
    assert settlement["recipient"] == challenge["sponsor"]
    assert settlement["amount"] == challenge["bounty"]["amount"]
    assert settlement_adapter.calls[0].operation == "refund"
    receipt = client.get(f"/v1/receipts/{flow['challenge_id']}").json()
    assert receipt["verdict"]["verdict"] == "rejected"
    assert receipt["settlement"]["operation"] == "refund"


@pytest.mark.parametrize("decision", ["needs_witness", "cannot_determine"])
def test_nonterminal_verdicts_do_not_pay(
    client, clock, private_key, settlement_adapter, decision
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0003"),
    ).json()
    resolved = record_verdict(
        client, private_key, clock, flow, challenge, submission, decision=decision
    )
    assert resolved.status_code == 201, resolved.text
    result = settle(client, resolved.json()["verdict"]["id"])
    assert result.status_code == 201
    settlement = result.json()["settlement"]
    assert settlement["operation"] == "no_payout"
    assert settlement["amount"] == 0
    assert settlement["txid"] is None
    receipt = client.get(f"/v1/receipts/{flow['challenge_id']}").json()
    assert receipt["status"] == "complete_no_payout"
    assert receipt["settlement"]["txid"] is None
    assert settlement_adapter.calls[0].operation == "no_payout"


def test_needs_witness_allows_a_new_active_submission_for_same_observer(
    client, clock, private_key
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0004"),
    ).json()
    resolved = record_verdict(
        client,
        private_key,
        clock,
        flow,
        challenge,
        submission,
        decision="needs_witness",
    )
    assert resolved.status_code == 201
    second = submit_evidence(
        client, clock, flow["challenge_id"], "c" * 64, key="submit-0002"
    )
    assert second.status_code == 201, second.text
    duplicate = submit_evidence(
        client, clock, flow["challenge_id"], "d" * 64, key="submit-0003"
    )
    assert duplicate.status_code == 409
    assert "active submission" in duplicate.json()["detail"]


@pytest.mark.parametrize("status", ["likely", "unlikely", "unavailable"])
def test_field_task_requires_insufficient_remote_evidence(make_app, clock, status):
    app = make_app(remote=StaticRemoteAdapter(status))
    with TestClient(app) as client:
        created = create_challenge(client, clock)
        challenge_id = created.json()["challenge"]["id"]
        remote = run_remote(client, challenge_id)
        assert remote.status_code == 201
        assert remote.json()["remote_evidence"]["status"] == status
        assert remote.json()["remote_evidence"]["is_cryptographic_proof"] is False
        task = create_task(client, challenge_id)
        assert task.status_code == 409
        submission = submit_evidence(client, clock, challenge_id)
        assert submission.status_code == 409
        assert client.get(f"/v1/receipts/{challenge_id}").status_code == 404
        state = client.get(f"/v1/challenges/{challenge_id}").json()["state"]
        assert state == f"remote_{status}"


def test_terminal_verdict_closes_challenge_to_new_submissions(
    client, clock, private_key
):
    flow = sealed_flow(client, clock)
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0005"),
    ).json()
    assert (
        record_verdict(
            client, private_key, clock, flow, challenge, submission
        ).status_code
        == 201
    )
    another = submit_evidence(
        client, clock, flow["challenge_id"], "e" * 64, key="submit-0002"
    )
    assert another.status_code == 409
    assert "resolved" in another.json()["detail"]


def test_challenge_creation_rejects_past_and_overlong_expiry(client, clock):
    past = create_challenge(
        client,
        clock,
        key="create-past",
        expires_at="2026-11-24T11:59:59.000000Z",
    )
    assert past.status_code == 422
    overlong = create_challenge(
        client, clock, key="create-long", expires_at="2027-01-01T00:00:00Z"
    )
    assert overlong.status_code == 422


def test_expiry_blocks_new_work_but_not_review_of_sealed_submission(
    client, clock, private_key
):
    created = create_challenge(client, clock)
    challenge_id = created.json()["challenge"]["id"]
    assert run_remote(client, challenge_id).status_code == 201
    assert create_task(client, challenge_id).status_code == 201
    clock.advance(hours=3)
    assert run_remote(client, challenge_id, key="remote-0002").status_code == 410
    assert create_task(client, challenge_id, key="task-0002").status_code == 410
    expired_submission = submit_evidence(client, clock, challenge_id)
    assert expired_submission.status_code == 410

    flow = sealed_flow(client, clock, prefix="review-")
    challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
    submission = client.get(
        f"/v1/submissions/{flow['submission_id']}",
        headers=headers("observer", "read-0006"),
    ).json()
    clock.advance(hours=3)
    resolved = record_verdict(client, private_key, clock, flow, challenge, submission)
    assert resolved.status_code == 201, resolved.text
    assert settle(client, resolved.json()["verdict"]["id"]).status_code == 201


def test_capture_window_and_location_are_enforced(client, clock):
    created = create_challenge(client, clock)
    challenge_id = created.json()["challenge"]["id"]
    assert run_remote(client, challenge_id).status_code == 201
    assert create_task(client, challenge_id).status_code == 201
    old = submit_evidence(
        client,
        clock,
        challenge_id,
        key="submit-old",
        public_metadata={
            "captured_at": "2026-11-24T11:59:59.000000Z",
            "public_location": "North trail public kiosk",
            "public_summary": "Old capture.",
        },
    )
    assert old.status_code == 422
    wrong_location = submit_evidence(
        client,
        clock,
        challenge_id,
        key="submit-location",
        public_metadata={
            "captured_at": "2026-11-24T12:00:00.000000Z",
            "public_location": "PRIVATE-EXACT-LOCATION",
            "public_summary": "Wrong task.",
        },
    )
    assert wrong_location.status_code == 422
