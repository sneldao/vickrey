from __future__ import annotations

import pytest
from app.adapters import SettlementRequest, SettlementResult
from app.qie import adapter_from_env, hash_bytes32, uuid_bytes32
from fastapi.testclient import TestClient

from tests.support import record_verdict, sealed_flow, settle


class FakeQieEscrowAdapter:
    name = "fake_qie_escrow"
    currency = "QIE"
    network = "qie_testnet"
    real_funds = False

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.submitted: list[dict] = []
        self.settled: list[SettlementRequest] = []

    def _event(self, event_type: str, tx_suffix: str, **kwargs) -> dict:
        return {
            "event_type": event_type,
            "challenge_id": kwargs.pop("challenge_id"),
            "submission_id": kwargs.pop("submission_id", None),
            "verdict_id": kwargs.pop("verdict_id", None),
            "tx_hash": "0x" + tx_suffix * 64,
            "chain_id": 1983,
            "contract_address": "0x0000000000000000000000000000000000000001",
            "sender_address": "0x0000000000000000000000000000000000000002",
            "network": self.network,
            "currency": "QIE",
            "amount": kwargs.pop("amount", 0),
            "payload": kwargs,
            "block_number": 42,
            "explorer_url": "https://testnet.qie.digital/tx/" + "0x" + tx_suffix * 64,
        }

    def create_challenge_escrow(self, **kwargs) -> dict:
        self.created.append(kwargs)
        return self._event(
            "challenge_created",
            "a",
            challenge_id=kwargs["challenge_id"],
            amount=kwargs["amount"],
            criteria_hash=kwargs["criteria_hash"],
        )

    def submit_evidence_escrow(self, **kwargs) -> dict:
        self.submitted.append(kwargs)
        return self._event(
            "evidence_submitted",
            "b",
            challenge_id=kwargs["challenge_id"],
            submission_id=kwargs["submission_id"],
            commitment=kwargs["commitment"],
        )

    def settle(self, request: SettlementRequest) -> SettlementResult:
        self.settled.append(request)
        if request.operation == "no_payout":
            return SettlementResult(
                status="no_payout",
                txid=None,
                amount=0,
                currency=request.currency,
                network=self.network,
                real_funds=False,
            )
        event = self._event(
            "challenge_resolved",
            "c",
            challenge_id=request.challenge_id,
            verdict_id=request.verdict_id,
            amount=request.amount,
            operation=request.operation,
        )
        return SettlementResult(
            status="settled",
            txid=event["tx_hash"],
            amount=request.amount,
            currency=request.currency,
            network=self.network,
            real_funds=False,
            chain_event=event,
        )


def test_qie_hooked_flow_records_lifecycle_transactions(
    make_app, remote_adapter, clock, private_key
):
    qie = FakeQieEscrowAdapter()
    app = make_app(remote=remote_adapter, settlement=qie)
    with TestClient(app) as client:
        flow = sealed_flow(client, clock)
        challenge = client.get(f"/v1/challenges/{flow['challenge_id']}").json()
        assert challenge["bounty"] == {"amount": 250, "currency": "QIE"}
        assert [event["event_type"] for event in challenge["chain_events"]] == [
            "challenge_created",
            "evidence_submitted",
        ]
        assert challenge["chain_events"][0]["tx_hash"].startswith("0x")
        assert challenge["chain_events"][0]["explorer_url"].startswith(
            "https://testnet.qie.digital/tx/"
        )
        assert qie.created[0]["sponsor"] == "claimant-1"
        assert qie.submitted[0]["observer"] == "observer-1"

        submission = client.get(
            f"/v1/submissions/{flow['submission_id']}",
            headers={
                "Authorization": "Bearer demo-observer-token-change-me",
                "Idempotency-Key": "qie-read-0001",
            },
        ).json()
        resolved = record_verdict(
            client, private_key, clock, flow, challenge, submission, decision="accepted"
        )
        assert resolved.status_code == 201, resolved.text
        verdict_id = resolved.json()["verdict"]["id"]
        settled = settle(client, verdict_id)
        assert settled.status_code == 201, settled.text
        settlement = settled.json()["settlement"]
        assert settlement["network"] == "qie_testnet"
        assert settlement["currency"] == "QIE"
        assert settlement["real_funds"] is False
        assert settlement["txid"] == "0x" + "c" * 64

        receipt = client.get(f"/v1/receipts/{flow['challenge_id']}").json()
        assert [event["event_type"] for event in receipt["chain_events"]] == [
            "challenge_created",
            "evidence_submitted",
            "challenge_resolved",
        ]
        assert receipt["settlement"]["network"] == "qie_testnet"
        limitation_text = " ".join(receipt["limitations"])
        assert "deterministic simulator" not in limitation_text
        assert "operator-controlled" in limitation_text


def test_qie_id_and_hash_conversion_validate_shape():
    assert uuid_bytes32("12345678-1234-1234-1234-123456789abc").hex() == (
        "0000000000000000000000000000000012345678123412341234123456789abc"
    )
    assert hash_bytes32("a" * 64) == bytes.fromhex("a" * 64)
    with pytest.raises(ValueError):
        uuid_bytes32("not-a-uuid")
    with pytest.raises(ValueError):
        hash_bytes32("ab")


def test_mainnet_adapter_requires_explicit_real_funds_ack():
    env = {
        "RECEIPTS_SETTLEMENT_ADAPTER": "qie_escrow",
        "RECEIPTS_QIE_NETWORK": "qie_mainnet",
        "RECEIPTS_QIE_CONTRACT_ADDRESS": "0x0000000000000000000000000000000000000001",
        "RECEIPTS_QIE_OPERATOR_PRIVATE_KEY": "0x" + "1" * 64,
    }
    with pytest.raises(ValueError, match="real mainnet funds"):
        adapter_from_env(env)
