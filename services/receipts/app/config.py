"""Environment-only configuration and server-held bearer principals.

A caller never chooses its role or subject. Both come from the token matched
against this configuration. Production has no implicit credentials.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

Role = Literal["claimant", "observer", "verifier", "settlement"]
ROLES: frozenset[str] = frozenset({"claimant", "observer", "verifier", "settlement"})
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/-]{24,256}$")
SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Explicit local-only credentials. They are usable only when RECEIPTS_MODE=demo.
DEMO_TOKENS: dict[str, tuple[str, str]] = {
    "demo-claimant-token-change-me": ("claimant", "claimant-1"),
    "demo-observer-token-change-me": ("observer", "observer-1"),
    "demo-verifier-token-change-me": ("verifier", "verifier-1"),
    "demo-settlement-token-change-me": ("settlement", "settlement-1"),
}
DEMO_VERIFIER_PUBLIC_KEY = bytes.fromhex(
    "9ec22a5e31611ca5ac59b8545e60000be7a50181a28460cb21a5b63ed19dc76d"
)


@dataclass(frozen=True)
class Principal:
    role: Role
    subject: str


@dataclass(frozen=True)
class Settings:
    mode: Literal["production", "demo"]
    database_path: str
    tokens: Mapping[str, Principal] = field(repr=False)
    verifier_public_key: Ed25519PublicKey = field(repr=False)
    verifier_key_fingerprint: str
    max_request_bytes: int = 65_536
    quota_per_hour: int = 120
    max_challenge_window_seconds: int = 30 * 24 * 60 * 60
    max_bounty_amount: int = 1_000_000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        mode = env.get("RECEIPTS_MODE", "production").strip().lower()
        if mode not in {"production", "demo"}:
            raise ValueError("RECEIPTS_MODE must be production or demo")

        raw_tokens = env.get("RECEIPTS_TOKENS_JSON")
        if raw_tokens is None:
            if mode == "production":
                raise ValueError("production requires RECEIPTS_TOKENS_JSON")
            token_entries = {
                token: {"role": role, "subject": subject}
                for token, (role, subject) in DEMO_TOKENS.items()
            }
        else:
            try:
                token_entries = json.loads(raw_tokens)
            except json.JSONDecodeError as exc:
                raise ValueError("RECEIPTS_TOKENS_JSON is not valid JSON") from exc
        if not isinstance(token_entries, dict) or not token_entries:
            raise ValueError("RECEIPTS_TOKENS_JSON must be a non-empty object")

        tokens: dict[str, Principal] = {}
        for token, entry in token_entries.items():
            if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
                raise ValueError("bearer tokens must be 24-256 URL-safe characters")
            if not isinstance(entry, dict) or set(entry) != {"role", "subject"}:
                raise ValueError("each token entry requires only role and subject")
            role = entry.get("role")
            subject = entry.get("subject")
            if role not in ROLES:
                raise ValueError("token role is not supported")
            if not isinstance(subject, str) or not SUBJECT_RE.fullmatch(subject):
                raise ValueError("token subject is invalid")
            if mode == "production" and len(token) < 32:
                raise ValueError(
                    "production bearer tokens must be at least 32 characters"
                )
            tokens[token] = Principal(role=role, subject=subject)
        missing = ROLES - {principal.role for principal in tokens.values()}
        if missing:
            raise ValueError(
                f"tokens are required for roles: {', '.join(sorted(missing))}"
            )

        raw_key = env.get("RECEIPTS_VERIFIER_PUBLIC_KEY")
        if raw_key is None:
            if mode == "production":
                raise ValueError("production requires RECEIPTS_VERIFIER_PUBLIC_KEY")
            public_key = Ed25519PublicKey.from_public_bytes(DEMO_VERIFIER_PUBLIC_KEY)
        else:
            public_key = _load_public_key(raw_key)

        import hashlib

        raw_public = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        fingerprint = hashlib.sha256(raw_public).hexdigest()
        database_path = env.get("RECEIPTS_DATABASE_PATH", "/data/receipts.db")
        if not database_path.strip():
            raise ValueError("RECEIPTS_DATABASE_PATH cannot be empty")
        return cls(
            mode=mode,
            database_path=database_path,
            tokens=MappingProxyType(tokens),
            verifier_public_key=public_key,
            verifier_key_fingerprint=fingerprint,
            max_request_bytes=_bounded_int(
                env, "RECEIPTS_MAX_REQUEST_BYTES", 65_536, 1_024, 1_048_576
            ),
            quota_per_hour=_bounded_int(
                env, "RECEIPTS_QUOTA_PER_HOUR", 120, 1, 100_000
            ),
            max_challenge_window_seconds=_bounded_int(
                env,
                "RECEIPTS_MAX_CHALLENGE_WINDOW_SECONDS",
                30 * 24 * 60 * 60,
                60,
                90 * 24 * 60 * 60,
            ),
            max_bounty_amount=_bounded_int(
                env, "RECEIPTS_MAX_BOUNTY_AMOUNT", 1_000_000, 1, 1_000_000_000
            ),
        )


def _bounded_int(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _load_public_key(raw: str) -> Ed25519PublicKey:
    try:
        if raw.strip().startswith("-----BEGIN"):
            key = serialization.load_pem_public_key(raw.strip().encode("ascii"))
        else:
            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw.strip()))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ValueError(
            "RECEIPTS_VERIFIER_PUBLIC_KEY must be Ed25519 PEM or hex"
        ) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("RECEIPTS_VERIFIER_PUBLIC_KEY must be Ed25519")  # noqa: TRY004
    return key
