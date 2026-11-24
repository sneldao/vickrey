"""Strict request models: unknown fields, raw records and exact locations fail closed."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX64_RE = r"^[0-9a-fA-F]{64}$"
SIG128_RE = r"^[0-9a-fA-F]{128}$"
ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
PRECISE_COORDINATE_RE = re.compile(
    r"[-+]?\d{1,3}\.\d+\s*[,;/]\s*[-+]?\d{1,3}\.\d+"
    r"|\b(?:lat|latitude|lon|longitude|lng)\b\s*[:=]?\s*[-+]?\d"
    r"|\d{1,3}\s*°"
    r"|\b\d{1,3}\.\d+\s*[NSEW]\b"
    r"|[-+]?\d{1,3}\.\d+\s+[-+]?\d{1,3}\.\d+\b",
    re.IGNORECASE,
)


def coarse_public_location(value: str) -> str:
    if PRECISE_COORDINATE_RE.search(value):
        raise ValueError("public_location must be a coarse label without coordinates")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmptyIn(StrictModel):
    """Optional empty body for action endpoints."""


class CriteriaIn(StrictModel):
    must_observe: str = Field(min_length=1, max_length=300)
    public_location: str = Field(min_length=1, max_length=120)
    radius_m: int = Field(ge=1, le=1_000)
    required_details: list[str] = Field(min_length=1, max_length=5)
    reject_if: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("public_location")
    @classmethod
    def public_location_is_coarse(cls, value: str) -> str:
        return coarse_public_location(value)

    @field_validator("required_details", "reject_if")
    @classmethod
    def bounded_items(cls, values: list[str]) -> list[str]:
        for value in values:
            if not 1 <= len(value.strip()) <= 200:
                raise ValueError("criteria list items must contain 1-200 characters")
        return values


class ChallengeIn(StrictModel):
    claim: str = Field(min_length=1, max_length=500)
    category: str = Field(pattern=ID_RE, max_length=64)
    criteria: CriteriaIn
    expires_at: datetime
    bounty_amount: int = Field(ge=1, le=1_000_000_000)

    @field_validator("expires_at")
    @classmethod
    def expiry_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value


class PublicMetadataIn(StrictModel):
    captured_at: datetime
    public_location: str = Field(min_length=1, max_length=120)
    observation_status: Literal["observed", "not_observed", "cannot_determine"]

    @field_validator("public_location")
    @classmethod
    def public_location_is_coarse(cls, value: str) -> str:
        return coarse_public_location(value)

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class SubmissionIn(StrictModel):
    commitment: str = Field(pattern=HEX64_RE)
    public_metadata: PublicMetadataIn


class VerdictIn(StrictModel):
    verdict_id: UUID
    challenge_id: UUID
    submission_id: UUID
    submission_version: int = Field(ge=1, le=1_000_000)
    commitment: str = Field(pattern=HEX64_RE)
    criteria_hash: str = Field(pattern=HEX64_RE)
    verdict: Literal["accepted", "rejected", "needs_witness", "cannot_determine"]
    policy_id: str = Field(pattern=ID_RE, max_length=64)
    policy_version: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=1, max_length=500)
    issued_at: datetime
    signature: str = Field(pattern=SIG128_RE)

    @field_validator("issued_at")
    @classmethod
    def issued_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must include a timezone")
        return value
