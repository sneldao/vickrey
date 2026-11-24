"""Canonical Ed25519 verdict signing shared by tests and the HTTP service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

VERDICT_SCHEMA = "reality-receipts.verifier-verdict.v1"


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_verdict_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": VERDICT_SCHEMA,
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


def verdict_signing_bytes(payload: Mapping[str, Any]) -> bytes:
    return dump_json(canonical_verdict_payload(payload)).encode("utf-8")


def verify_verdict_signature(
    public_key: Ed25519PublicKey, payload: Mapping[str, Any], signature_hex: str
) -> bool:
    try:
        signature = bytes.fromhex(signature_hex)
        if len(signature) != 64:
            return False
        public_key.verify(signature, verdict_signing_bytes(payload))
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return False
    return True


def public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return hashlib.sha256(raw).hexdigest()
