"""QIE EVM escrow adapter for the hackathon settlement path.

The adapter is deliberately narrow: it talks only to RealityReceiptsEscrow and
returns mined transaction metadata. Private keys come from the process
environment and are never accepted in request bodies or written to the database.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.adapters import SettlementRequest, SettlementResult
from app.signing import dump_json

QIE_CURRENCY = "QIE"
QIE_TESTNET = "qie_testnet"
QIE_MAINNET = "qie_mainnet"
QIE_NETWORKS = {
    QIE_TESTNET: {
        "chain_id": 1983,
        "rpc_url": "https://rpc4testnet.qie.digital/",
        "explorer": "https://testnet.qie.digital",
    },
    QIE_MAINNET: {
        "chain_id": 1990,
        "rpc_url": "https://rpc1mainnet.qie.digital/",
        "explorer": "https://mainnet.qie.digital",
    },
}
MAINNET_ACK = "I_APPROVE_REAL_QIE_MAINNET_FUNDS"
ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "RealityReceiptsEscrow.json"


def uuid_bytes32(value: str) -> bytes:
    raw = value.replace("-", "")
    if len(raw) != 32:
        raise ValueError("QIE external ids must be UUID-shaped")
    # UUIDs are 16 bytes; left-pad them into the contract's bytes32 external id.
    return b"\x00" * 16 + bytes.fromhex(raw)


def hash_bytes32(value: str) -> bytes:
    if len(value) != 64:
        raise ValueError("QIE hashes must be 64 lowercase hex characters")
    return bytes.fromhex(value)


def _tx_hash_hex(value: Any) -> str:
    if hasattr(value, "hex"):
        text = value.hex()
    else:
        text = str(value)
    return text if text.startswith("0x") else "0x" + text


class QieEscrowSettlementAdapter:
    """Synchronous mined-transaction adapter for the minimal escrow contract."""

    name = "qie_reality_receipts_escrow"
    currency = QIE_CURRENCY
    amount_unit = "wei"

    def __init__(
        self,
        *,
        rpc_url: str,
        contract_address: str,
        private_key: str,
        network: str,
        chain_id: int,
        explorer_base_url: str,
        timeout_seconds: int = 90,
    ) -> None:
        if network not in QIE_NETWORKS:
            raise ValueError("network must be qie_testnet or qie_mainnet")
        try:
            from web3 import Web3
        except ImportError as exc:
            raise RuntimeError("web3.py is required for QIE settlement") from exc

        self.network = network
        self.chain_id = int(chain_id)
        self.real_funds = network == QIE_MAINNET
        self.explorer_base_url = explorer_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.w3 = Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout_seconds})
        )
        connected_chain = int(self.w3.eth.chain_id)
        if connected_chain != self.chain_id:
            raise ValueError(
                f"QIE RPC chain_id {connected_chain} does not match configured {self.chain_id}"
            )
        if not self.w3.is_address(contract_address):
            raise ValueError("QIE contract address is invalid")
        self.contract_address = self.w3.to_checksum_address(contract_address)
        self.account = self.w3.eth.account.from_key(private_key)
        artifact = json.loads(ARTIFACT_PATH.read_text())
        self.contract = self.w3.eth.contract(
            address=self.contract_address, abi=artifact["abi"]
        )

    @property
    def operator_address(self) -> str:
        return self.account.address

    def explorer_tx_url(self, tx_hash: str) -> str:
        return f"{self.explorer_base_url}/tx/{tx_hash}"

    def create_challenge_escrow(
        self,
        *,
        challenge_id: str,
        criteria_hash: str,
        expires_at_epoch: int,
        amount: int,
        sponsor: str,
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("QIE escrow amount must be positive wei")
        sponsor_address = self._address(sponsor, "sponsor")
        if sponsor_address != self.account.address:
            raise ValueError(
                "the QIE MVP requires the configured sponsor subject to be the operator wallet"
            )
        fn = self.contract.functions.createChallenge(
            uuid_bytes32(challenge_id),
            hash_bytes32(criteria_hash),
            int(expires_at_epoch),
        )
        return self._transact(
            fn,
            value=amount,
            event_type="challenge_created",
            challenge_id=challenge_id,
            payload={
                "criteria_hash": criteria_hash,
                "expires_at_epoch": int(expires_at_epoch),
                "amount_wei": amount,
                "sponsor": sponsor_address,
            },
        )

    def submit_evidence_escrow(
        self,
        *,
        challenge_id: str,
        submission_id: str,
        commitment: str,
        observer: str,
    ) -> dict[str, Any]:
        observer_address = self._address(observer, "observer")
        fn = self.contract.functions.submitEvidenceFor(
            uuid_bytes32(challenge_id),
            uuid_bytes32(submission_id),
            hash_bytes32(commitment),
            observer_address,
        )
        return self._transact(
            fn,
            value=0,
            event_type="evidence_submitted",
            challenge_id=challenge_id,
            submission_id=submission_id,
            payload={
                "commitment": commitment,
                "observer": observer_address,
                "relay": "operator_submitEvidenceFor",
            },
        )

    def settle(self, request: SettlementRequest) -> SettlementResult:
        if request.currency != QIE_CURRENCY:
            raise ValueError("QIE escrow adapter only settles QIE")
        if request.operation == "no_payout":
            # Non-terminal off-chain verdicts do not close the on-chain escrow in
            # this MVP. The escrow remains recoverable through contract expiry.
            return SettlementResult(
                status="no_payout",
                txid=None,
                amount=0,
                currency=request.currency,
                network=self.network,
                real_funds=self.real_funds,
            )
        if request.operation not in {"payout", "refund"}:
            raise ValueError("unsupported settlement operation")

        challenge = self.contract.functions.getChallenge(
            uuid_bytes32(request.challenge_id)
        ).call()
        sponsor = self.w3.to_checksum_address(challenge[0])
        amount = int(challenge[1])
        observer = self.w3.to_checksum_address(challenge[7])
        if amount != request.amount:
            raise ValueError("off-chain bounty does not match the QIE escrow amount")
        if request.operation == "payout":
            recipient = self._address(request.recipient, "payout recipient")
            if recipient != observer:
                raise ValueError(
                    "payout recipient does not match the on-chain observer"
                )
            resolution = 1
        else:
            recipient = self._address(request.recipient, "refund recipient")
            if recipient != sponsor:
                raise ValueError("refund recipient does not match the on-chain sponsor")
            resolution = 2

        proof_hash = hashlib.sha256(
            dump_json(
                {
                    "schema": "reality-receipts.chain-resolution-proof.v1",
                    "verdict_id": request.verdict_id,
                    "challenge_id": request.challenge_id,
                    "operation": request.operation,
                }
            ).encode("utf-8")
        ).hexdigest()
        fn = self.contract.functions.resolveChallenge(
            uuid_bytes32(request.challenge_id), resolution, hash_bytes32(proof_hash)
        )
        event = self._transact(
            fn,
            value=0,
            event_type="challenge_resolved",
            challenge_id=request.challenge_id,
            verdict_id=request.verdict_id,
            payload={
                "operation": request.operation,
                "resolution": resolution,
                "proof_hash": proof_hash,
                "amount_wei": amount,
                "recipient": recipient,
            },
        )
        return SettlementResult(
            status="settled",
            txid=event["tx_hash"],
            amount=amount,
            currency=request.currency,
            network=self.network,
            real_funds=self.real_funds,
            chain_event=event,
        )

    def _address(self, value: str, label: str) -> str:
        if not self.w3.is_address(value):
            raise ValueError(f"{label} must be a QIE/EVM address")
        return self.w3.to_checksum_address(value)

    def _transact(
        self,
        fn: Any,
        *,
        value: int,
        event_type: str,
        challenge_id: str,
        payload: dict[str, Any],
        submission_id: str | None = None,
        verdict_id: str | None = None,
    ) -> dict[str, Any]:
        tx = fn.build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "chainId": self.chain_id,
                "value": value,
            }
        )
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = self.w3.eth.gas_price
        signed = self.w3.eth.account.sign_transaction(tx, private_key=self.account.key)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        receipt = self.w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=self.timeout_seconds
        )
        if int(receipt["status"]) != 1:
            raise RuntimeError("QIE transaction reverted")
        tx_hex = _tx_hash_hex(tx_hash)
        amount = int(payload.get("amount_wei", 0))
        return {
            "event_type": event_type,
            "challenge_id": challenge_id,
            "submission_id": submission_id,
            "verdict_id": verdict_id,
            "tx_hash": tx_hex,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "sender_address": self.account.address,
            "network": self.network,
            "currency": QIE_CURRENCY,
            "amount": amount,
            "payload": payload,
            "block_number": int(receipt["blockNumber"]),
            "explorer_url": self.explorer_tx_url(tx_hex),
        }


def adapter_from_env(
    env: Mapping[str, str] | None = None,
) -> QieEscrowSettlementAdapter | None:
    values = os.environ if env is None else env
    kind = values.get("RECEIPTS_SETTLEMENT_ADAPTER", "simulator").strip().lower()
    if kind in {"", "simulator", "deterministic_testnet_simulator"}:
        return None
    if kind not in {"qie", "qie_escrow", "qie_reality_receipts_escrow"}:
        raise ValueError("RECEIPTS_SETTLEMENT_ADAPTER must be simulator or qie_escrow")
    network = values.get("RECEIPTS_QIE_NETWORK", QIE_TESTNET).strip().lower()
    if network not in QIE_NETWORKS:
        raise ValueError("RECEIPTS_QIE_NETWORK must be qie_testnet or qie_mainnet")
    defaults = QIE_NETWORKS[network]
    contract_address = values.get("RECEIPTS_QIE_CONTRACT_ADDRESS", "").strip()
    private_key = values.get("RECEIPTS_QIE_OPERATOR_PRIVATE_KEY", "").strip()
    if not contract_address:
        raise ValueError("QIE settlement requires RECEIPTS_QIE_CONTRACT_ADDRESS")
    if not private_key:
        raise ValueError("QIE settlement requires RECEIPTS_QIE_OPERATOR_PRIVATE_KEY")
    if network == QIE_MAINNET and values.get("RECEIPTS_QIE_MAINNET_ACK") != MAINNET_ACK:
        raise ValueError(
            "real mainnet funds require RECEIPTS_QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS"
        )
    return QieEscrowSettlementAdapter(
        rpc_url=values.get("RECEIPTS_QIE_RPC_URL", defaults["rpc_url"]).strip(),
        contract_address=contract_address,
        private_key=private_key,
        network=network,
        chain_id=int(values.get("RECEIPTS_QIE_CHAIN_ID", str(defaults["chain_id"]))),
        explorer_base_url=values.get(
            "RECEIPTS_QIE_EXPLORER_URL", defaults["explorer"]
        ).strip(),
        timeout_seconds=int(values.get("RECEIPTS_QIE_TX_TIMEOUT_SECONDS", "90")),
    )
