"""Narrow remote-evidence and settlement ports with deterministic demo adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol

from app.signing import dump_json

RemoteStatus = Literal["likely", "unlikely", "insufficient", "unavailable"]
SettlementOperation = Literal["payout", "refund", "no_payout"]
SIMULATED_CURRENCY = "SIMULATED_TESTNET_CREDITS"
SIMULATED_NETWORK = "simulated_testnet"


@dataclass(frozen=True)
class RemoteEvidenceInput:
    challenge_id: str
    claim: str
    category: str
    criteria_hash: str
    expires_at: str


@dataclass(frozen=True)
class RemoteEvidenceResult:
    status: RemoteStatus
    summary: str
    provider: str
    provider_version: str
    source_label: str


class RemoteEvidenceAdapter(Protocol):
    provider: str
    provider_version: str

    def evaluate(self, evidence_input: RemoteEvidenceInput) -> RemoteEvidenceResult: ...


class DeterministicDemoRemoteEvidenceAdapter:
    """Synthetic context only; the input hash selects one of four demo states."""

    provider = "deterministic_demo"
    provider_version = "demo-1"
    source_label = "deterministic_synthetic_demo"

    def evaluate(self, evidence_input: RemoteEvidenceInput) -> RemoteEvidenceResult:
        material = dump_json(
            {
                "provider": self.provider,
                "version": self.provider_version,
                "challenge_id": evidence_input.challenge_id,
                "claim": evidence_input.claim,
                "category": evidence_input.category,
                "criteria_hash": evidence_input.criteria_hash,
                "expires_at": evidence_input.expires_at,
            }
        )
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        statuses: tuple[RemoteStatus, ...] = (
            "likely",
            "unlikely",
            "insufficient",
            "unavailable",
        )
        status = statuses[digest[0] % len(statuses)]
        summaries: dict[RemoteStatus, str] = {
            "likely": "Synthetic context rates the claim likely; this is not proof.",
            "unlikely": "Synthetic context rates the claim unlikely; this is not proof.",
            "insufficient": "Synthetic context cannot resolve this bounded field claim.",
            "unavailable": "The synthetic demo provider is unavailable for this case.",
        }
        return RemoteEvidenceResult(
            status=status,
            summary=summaries[status],
            provider=self.provider,
            provider_version=self.provider_version,
            source_label=self.source_label,
        )


class FieldPathDemoRemoteEvidenceAdapter:
    """Synthetic context fixed to the field-evidence path for repeatable demos."""

    provider = "deterministic_demo_field_path"
    provider_version = "demo-1"
    source_label = "deterministic_synthetic_demo"

    def evaluate(self, evidence_input: RemoteEvidenceInput) -> RemoteEvidenceResult:
        return RemoteEvidenceResult(
            status="insufficient",
            summary="Synthetic context cannot resolve this bounded field claim.",
            provider=self.provider,
            provider_version=self.provider_version,
            source_label=self.source_label,
        )


@dataclass(frozen=True)
class SettlementRequest:
    settlement_id: str
    challenge_id: str
    verdict_id: str
    operation: SettlementOperation
    amount: int
    currency: str
    recipient: str


@dataclass(frozen=True)
class SettlementResult:
    status: Literal["settled", "no_payout"]
    txid: str | None
    amount: int
    currency: str
    network: str
    real_funds: bool = False
    chain_event: dict | None = None


class SettlementAdapter(Protocol):
    name: str

    def settle(self, request: SettlementRequest) -> SettlementResult: ...


class DeterministicTestnetSimulator:
    """No wallet, RPC, chain or funds. The same operation always yields one txid."""

    name = "deterministic_testnet_simulator"
    currency = SIMULATED_CURRENCY
    amount_unit = "simulated_credit"
    network = SIMULATED_NETWORK
    real_funds = False

    def settle(self, request: SettlementRequest) -> SettlementResult:
        if request.operation == "no_payout":
            return SettlementResult(
                status="no_payout",
                txid=None,
                amount=0,
                currency=request.currency,
                network=SIMULATED_NETWORK,
                real_funds=False,
            )
        if request.operation not in {"payout", "refund"}:
            raise ValueError("unsupported settlement operation")
        material = dump_json(
            {
                "adapter": self.name,
                "settlement_id": request.settlement_id,
                "challenge_id": request.challenge_id,
                "verdict_id": request.verdict_id,
                "operation": request.operation,
                "amount": request.amount,
                "currency": request.currency,
                "recipient": request.recipient,
            }
        )
        txid = "sim_" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        return SettlementResult(
            status="settled",
            txid=txid,
            amount=request.amount,
            currency=request.currency,
            network=SIMULATED_NETWORK,
            real_funds=False,
        )
