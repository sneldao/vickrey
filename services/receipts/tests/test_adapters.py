from __future__ import annotations

import hashlib

from app.adapters import (
    SIMULATED_CURRENCY,
    DeterministicDemoRemoteEvidenceAdapter,
    DeterministicTestnetSimulator,
    FieldPathDemoRemoteEvidenceAdapter,
    RemoteEvidenceInput,
    SettlementRequest,
)
from app.signing import dump_json

from tests.support import create_challenge


def test_demo_remote_provider_is_deterministic_and_can_return_every_honest_state():
    adapter = DeterministicDemoRemoteEvidenceAdapter()
    seen = set()
    for nonce in range(100):
        evidence_input = RemoteEvidenceInput(
            challenge_id=f"challenge-{nonce}",
            claim=f"Bounded public claim {nonce}",
            category="public_notice",
            criteria_hash=f"{nonce:064x}",
            expires_at="2026-11-24T14:00:00.000000Z",
        )
        first = adapter.evaluate(evidence_input)
        second = adapter.evaluate(evidence_input)
        assert first == second
        assert first.source_label == "deterministic_synthetic_demo"
        assert first.provider == "deterministic_demo"
        seen.add(first.status)
    assert seen == {"likely", "unlikely", "insufficient", "unavailable"}


def test_field_path_demo_remote_provider_repeatably_enters_field_evidence():
    adapter = FieldPathDemoRemoteEvidenceAdapter()
    evidence_input = RemoteEvidenceInput(
        challenge_id="challenge-repeatable",
        claim="Bounded public claim",
        category="public_notice",
        criteria_hash="0" * 64,
        expires_at="2026-11-24T14:00:00.000000Z",
    )
    first = adapter.evaluate(evidence_input)
    second = adapter.evaluate(evidence_input)
    assert first == second
    assert first.status == "insufficient"
    assert first.provider == "deterministic_demo_field_path"
    assert first.source_label == "deterministic_synthetic_demo"


def test_simulator_is_deterministic_idempotent_and_never_moves_real_funds():
    adapter = DeterministicTestnetSimulator()
    request = SettlementRequest(
        settlement_id="settlement-1",
        challenge_id="challenge-1",
        verdict_id="verdict-1",
        operation="payout",
        amount=250,
        currency=SIMULATED_CURRENCY,
        recipient="observer-1",
    )
    first = adapter.settle(request)
    second = adapter.settle(request)
    assert first == second
    assert first.status == "settled"
    assert first.txid.startswith("sim_")
    assert first.amount == 250
    assert first.network == "simulated_testnet"
    assert first.real_funds is False
    no_pay = adapter.settle(
        SettlementRequest(
            settlement_id="settlement-2",
            challenge_id="challenge-1",
            verdict_id="verdict-2",
            operation="no_payout",
            amount=0,
            currency=SIMULATED_CURRENCY,
            recipient="none",
        )
    )
    assert no_pay.status == "no_payout"
    assert no_pay.txid is None
    assert no_pay.amount == 0
    assert no_pay.real_funds is False


def test_criteria_hash_is_server_computed_from_canonical_versioned_criteria(
    client, clock
):
    response = create_challenge(client, clock, key="hash-check-1")
    assert response.status_code == 201
    challenge = response.json()["challenge"]
    material = dump_json(
        {"schema": "reality-receipts.criteria.v1", "criteria": challenge["criteria"]}
    )
    expected = hashlib.sha256(material.encode("utf-8")).hexdigest()
    assert challenge["criteria_hash"] == expected
    assert challenge["sponsor"] == "claimant-1"
    assert challenge["bounty"] == {
        "amount": 250,
        "currency": "SIMULATED_TESTNET_CREDITS",
    }
