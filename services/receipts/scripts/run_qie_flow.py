#!/usr/bin/env python3
"""Run one operator-controlled Reality Receipts flow over HTTP.

Secrets are read only from the environment and are never written to the output:
  RECEIPTS_CLAIMANT_TOKEN, RECEIPTS_OBSERVER_TOKEN, RECEIPTS_VERIFIER_TOKEN,
  RECEIPTS_SETTLEMENT_TOKEN, RECEIPTS_VERIFIER_PRIVATE_KEY_PKCS8_BASE64

The script reproduces the browser demo's local seal boundary: it creates a
one-entry Vickrey seal locally, sends only the commitment and bounded public
metadata, signs the explicit demo verdict policy, then fetches the public
receipt. It is intended for operator-controlled QIE proof runs, not as a public
unauthenticated workflow.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

TOKEN_ENV = {
    "claimant": "RECEIPTS_CLAIMANT_TOKEN",
    "observer": "RECEIPTS_OBSERVER_TOKEN",
    "verifier": "RECEIPTS_VERIFIER_TOKEN",
    "settlement": "RECEIPTS_SETTLEMENT_TOKEN",
}
LOCAL_RECORD_SCHEMA = "vickrey.reality-receipts.local-sealed-record.v1"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def verdict_signing_bytes(payload: dict[str, Any]) -> bytes:
    canonical = {
        "schema": "reality-receipts.verifier-verdict.v1",
        "verdict_id": str(payload["verdict_id"]),
        "challenge_id": str(payload["challenge_id"]),
        "submission_id": str(payload["submission_id"]),
        "submission_version": int(payload["submission_version"]),
        "commitment": str(payload["commitment"]).lower(),
        "criteria_hash": str(payload["criteria_hash"]).lower(),
        "verdict": payload["verdict"],
        "policy_id": payload["policy_id"],
        "policy_version": int(payload["policy_version"]),
        "reason": str(payload["reason"]).strip(),
        "issued_at": iso_utc(payload["issued_at"]),
    }
    return canonical_json(canonical).encode("utf-8")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def load_verifier_key() -> Ed25519PrivateKey:
    encoded = os.environ.get("RECEIPTS_VERIFIER_PRIVATE_KEY_PKCS8_BASE64", "").strip()
    if not encoded:
        raise SystemExit("RECEIPTS_VERIFIER_PRIVATE_KEY_PKCS8_BASE64 is required")
    try:
        key = serialization.load_der_private_key(base64.b64decode(encoded), None)
    except Exception as exc:
        raise SystemExit("verifier private key is not valid PKCS#8 DER base64") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("verifier private key must be Ed25519")
    return key


def token(role: str) -> str:
    value = os.environ.get(TOKEN_ENV[role], "").strip()
    if not value:
        raise SystemExit(f"{TOKEN_ENV[role]} is required")
    return value


def headers(role: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(role)}",
        "Idempotency-Key": f"rr-operator-{role}-{uuid.uuid4()}",
    }


def request(
    method: str,
    base_url: str,
    path: str,
    *,
    role: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{base_url.rstrip('/')}{path}",
        headers=headers(role) if role else {},
        json=body,
        timeout=45,
    )
    if response.status_code >= 400:
        detail = response.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"{method} {path} failed: HTTP {response.status_code}: {detail}"
        )
    return response.json()


def seal_observation(
    *,
    challenge: dict[str, Any],
    task: dict[str, Any],
    outcome: str,
    observation_note: str,
    observed_at: datetime,
) -> dict[str, Any]:
    key = Ed25519PrivateKey.generate()
    payload = {
        "schema": "reality-receipts.public-observation.v1",
        "challenge_id": challenge["id"],
        "task_id": task["id"],
        "criteria_hash": challenge["criteria_hash"],
        "claim": challenge["claim"],
        "category": challenge["category"],
        "public_location": challenge["criteria"]["public_location"],
        "criteria": challenge["criteria"],
        "outcome": outcome,
        "public_summary": observation_note,
    }
    body = {
        "prev": None,
        "observed_at": iso_utc(observed_at),
        "location": None,
        "model_id": "human-public-notice-demo-v1",
        "payload": payload,
    }
    commitment = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    signature = b64url(key.sign(commitment.encode("utf-8")))
    public_key = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    sealed_entry = {
        **body,
        "hash": commitment,
        "signature": signature,
    }
    public_metadata = {
        "captured_at": iso_utc(observed_at),
        "public_location": challenge["criteria"]["public_location"],
        "observation_status": outcome,
    }
    return {
        "schema": LOCAL_RECORD_SCHEMA,
        "challenge_id": challenge["id"],
        "task_id": task["id"],
        "submission_id": None,
        "captured_at": iso_utc(observed_at),
        "criteria_hash": challenge["criteria_hash"],
        "observer_public_key": b64url(public_key),
        "observer_public_key_encoding": "base64url-spki",
        "commitment": commitment,
        "sealed_entry": sealed_entry,
        "public_metadata": public_metadata,
        "seal_verification": {"ok": True, "brokenAt": None},
        "service_boundary": {
            "sent_fields": ["commitment", "public_metadata"],
            "raw_observation_received": False,
            "precise_location_received": False,
            "observer_private_key_retained": False,
        },
    }


def demo_policy_decision(
    *,
    outcome: str,
    observation_note: str,
    reject_if: list[str],
) -> tuple[str, str]:
    note = observation_note.lower()
    matched = [item for item in reject_if if item.lower() in note]
    if outcome == "observed" and not matched:
        return (
            "accepted",
            "Operator proof-run policy public-notice-v1 accepted the claim: the seal verified, the public task and capture window matched, the observer marked it observed, and no reject-if text matched. The service did not verify the raw record.",
        )
    if outcome == "not_observed" or matched:
        return (
            "rejected",
            "Operator proof-run policy public-notice-v1 rejected the claim because the observation outcome or reject-if criteria did not satisfy the public notice policy.",
        )
    return (
        "cannot_determine",
        "Operator proof-run policy public-notice-v1 could not determine the claim from the sealed observation outcome.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RECEIPTS_BASE_URL", "http://127.0.0.1:8099"),
    )
    parser.add_argument("--bounty", type=int, default=1_000_000_000_000_000)
    parser.add_argument("--expires-hours", type=float, default=2.0)
    parser.add_argument(
        "--claim", default="The public north-trail kiosk notice is present today."
    )
    parser.add_argument(
        "--observation-note",
        default="The notice title and visible posting date were readable at the public kiosk.",
    )
    parser.add_argument(
        "--outcome",
        choices=["observed", "not_observed", "cannot_determine"],
        default="observed",
    )
    parser.add_argument(
        "--output",
        help="write the non-secret local record and public receipt JSON here",
    )
    parser.add_argument(
        "--approve-mainnet",
        action="store_true",
        help="required when the service reports qie_mainnet/real funds",
    )
    args = parser.parse_args()

    health = request("GET", args.base_url, "/healthz")
    network = health.get("settlement_network")
    if network not in {"qie_testnet", "qie_mainnet"}:
        raise SystemExit(f"unsupported settlement network for this script: {network}")
    if network == "qie_mainnet" and not args.approve_mainnet:
        raise SystemExit("refusing qie_mainnet without --approve-mainnet")
    if health.get("real_funds") is True and not args.approve_mainnet:
        raise SystemExit("refusing real funds without --approve-mainnet")

    now = datetime.now(UTC)
    challenge_body = {
        "claim": args.claim,
        "category": "public_notice",
        "criteria": {
            "must_observe": "Read the posted notice at the public kiosk.",
            "public_location": "North trail public kiosk",
            "radius_m": 25,
            "required_details": ["notice title", "visible posting date"],
            "reject_if": ["notice is absent", "notice is unreadable"],
        },
        "expires_at": iso_utc(now + timedelta(hours=args.expires_hours)),
        "bounty_amount": args.bounty,
    }
    created = request(
        "POST", args.base_url, "/v1/challenges", role="claimant", body=challenge_body
    )
    challenge = created["challenge"]
    challenge_id = challenge["id"]
    print(f"challenge {challenge_id}")

    request(
        "POST",
        args.base_url,
        f"/v1/challenges/{challenge_id}/remote-evidence",
        role="claimant",
        body={},
    )
    print("remote-evidence insufficient")

    task_response = request(
        "POST",
        args.base_url,
        f"/v1/challenges/{challenge_id}/field-task",
        role="claimant",
        body={},
    )
    task = task_response["field_task"]
    print(f"field-task {task['id']}")

    record = seal_observation(
        challenge=challenge,
        task=task,
        outcome=args.outcome,
        observation_note=args.observation_note,
        observed_at=datetime.now(UTC),
    )
    submission_response = request(
        "POST",
        args.base_url,
        f"/v1/challenges/{challenge_id}/submissions",
        role="observer",
        body={
            "commitment": record["commitment"],
            "public_metadata": record["public_metadata"],
        },
    )
    submission = submission_response["submission"]
    record["submission_id"] = submission["id"]
    print(f"submission {submission['id']} commitment {record['commitment']}")

    verdict_value, reason = demo_policy_decision(
        outcome=args.outcome,
        observation_note=args.observation_note,
        reject_if=challenge["criteria"]["reject_if"],
    )
    verdict_unsigned = {
        "verdict_id": str(uuid.uuid4()),
        "challenge_id": challenge_id,
        "submission_id": submission["id"],
        "submission_version": submission.get("version", 1),
        "commitment": record["commitment"],
        "criteria_hash": challenge["criteria_hash"],
        "verdict": verdict_value,
        "policy_id": "public-notice-v1",
        "policy_version": 1,
        "reason": reason,
        "issued_at": datetime.now(UTC),
    }
    verifier_key = load_verifier_key()
    verdict = {
        **verdict_unsigned,
        "issued_at": iso_utc(verdict_unsigned["issued_at"]),
        "signature": verifier_key.sign(verdict_signing_bytes(verdict_unsigned)).hex(),
    }
    verdict_response = request(
        "POST",
        args.base_url,
        f"/v1/submissions/{submission['id']}/verdicts",
        role="verifier",
        body=verdict,
    )
    verdict_id = verdict_response["verdict"]["id"]
    print(f"verdict {verdict_id} {verdict_value}")

    settlement_response = request(
        "POST",
        args.base_url,
        f"/v1/verdicts/{verdict_id}/settlement",
        role="settlement",
        body={},
    )
    settlement = settlement_response["settlement"]
    print(f"settlement {settlement['status']} {settlement.get('txid')}")

    receipt = request("GET", args.base_url, f"/v1/receipts/{challenge_id}")
    chain_events = receipt.get("chain_events", [])
    print(f"receipt {receipt['status']} chain_events {len(chain_events)}")
    for event in chain_events:
        print(
            f"{event['event_type']} {event.get('tx_hash')} {event.get('explorer_url')}"
        )

    if args.output:
        output = {
            "health": health,
            "local_record": record,
            "public_receipt": receipt,
        }
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        print(f"output {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
