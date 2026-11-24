"""Workflow orchestration. All authority comes from configured principals."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.adapters import (
    SIMULATED_CURRENCY,
    DeterministicDemoRemoteEvidenceAdapter,
    DeterministicTestnetSimulator,
    RemoteEvidenceAdapter,
    RemoteEvidenceInput,
    RemoteEvidenceResult,
    SettlementAdapter,
    SettlementRequest,
)
from app.config import Principal, Settings
from app.db import Database, MutationResult
from app.errors import (
    Conflict,
    Forbidden,
    Gone,
    InvalidSignature,
    NotFound,
    ServiceError,
)
from app.models import ChallengeIn, SubmissionIn, VerdictIn
from app.signing import (
    canonical_verdict_payload,
    dump_json,
    iso_utc,
    verify_verdict_signature,
)

logger = logging.getLogger("receipts")

CRITERIA_SCHEMA = "reality-receipts.criteria.v1"
BRIEF_SCHEMA = "reality-receipts.evidence-brief.v1"
RECEIPT_SCHEMA = "reality-receipts.public-receipt.v1"
TERMINAL_VERDICTS = {"accepted", "rejected"}


class _VerdictRejected(Exception):
    def __init__(self, error: ServiceError, outcome: str, reason: str) -> None:
        super().__init__(reason)
        self.error = error
        self.outcome = outcome
        self.reason = reason


class ReceiptService:
    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        remote_adapter: RemoteEvidenceAdapter | None = None,
        settlement_adapter: SettlementAdapter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.db = database or Database(settings.database_path)
        self.remote_adapter = remote_adapter or DeterministicDemoRemoteEvidenceAdapter()
        self.settlement_adapter = settlement_adapter or DeterministicTestnetSimulator()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("service clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _quota(self, conn: sqlite3.Connection, principal: Principal) -> None:
        self.db.consume_quota(
            conn=conn,
            subject=principal.subject,
            limit=self.settings.quota_per_hour,
            now=self._now(),
        )

    @staticmethod
    def request_hash(
        operation: str, resource_path: str, payload: dict[str, Any]
    ) -> str:
        material = dump_json(
            {"operation": operation, "resource_path": resource_path, "payload": payload}
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _require_not_expired(self, row: sqlite3.Row, now: datetime) -> None:
        if now >= self._parse_time(row["expires_at"]):
            raise Gone("challenge has expired")

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _criteria_hash(criteria: dict[str, Any]) -> str:
        material = dump_json({"schema": CRITERIA_SCHEMA, "criteria": criteria})
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _brief(
        payload: ChallengeIn, criteria: dict[str, Any], expires_at: str
    ) -> dict[str, Any]:
        return {
            "schema": BRIEF_SCHEMA,
            "claim": payload.claim,
            "objective": criteria["must_observe"],
            "public_location": criteria["public_location"],
            "radius_m": criteria["radius_m"],
            "deadline": expires_at,
            "required_details": criteria["required_details"],
            "counts_against": criteria["reject_if"],
            "bounty": {"amount": payload.bounty_amount, "currency": SIMULATED_CURRENCY},
            "safety_boundary": "Public, bounded tasks only; no people, interiors or minors.",
        }

    @staticmethod
    def _challenge_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "claimant": row["claimant_subject"],
            "sponsor": row["sponsor_subject"],
            "claim": row["claim_text"],
            "category": row["category"],
            "criteria": json.loads(row["criteria_json"]),
            "criteria_hash": row["criteria_hash"],
            "brief": json.loads(row["brief_json"]),
            "bounty": {"amount": row["bounty_amount"], "currency": row["currency"]},
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "version": row["version"],
        }

    @staticmethod
    def _remote_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "challenge_id": row["challenge_id"],
            "status": row["status"],
            "summary": row["summary"],
            "provider": row["provider"],
            "provider_version": row["provider_version"],
            "source_label": row["source_label"],
            "input_hash": row["input_hash"],
            "is_cryptographic_proof": False,
            "checked_at": row["checked_at"],
        }

    @staticmethod
    def _task_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "challenge_id": row["challenge_id"],
            "remote_evidence_id": row["remote_evidence_id"],
            "public_location": row["public_location"],
            "radius_m": row["radius_m"],
            "evidence_requirements": json.loads(row["evidence_requirements_json"]),
            "reject_if": json.loads(row["reject_if_json"]),
            "bounty": {"amount": row["bounty_amount"], "currency": row["currency"]},
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "version": row["version"],
        }

    @staticmethod
    def _submission_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "challenge_id": row["challenge_id"],
            "task_id": row["task_id"],
            "observer": row["observer_subject"],
            "commitment": row["commitment"],
            "public_metadata": json.loads(row["public_metadata_json"]),
            "submitted_at": row["submitted_at"],
            "version": row["version"],
            "status": row["status"],
        }

    @staticmethod
    def _verdict_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "verdict_id": row["verdict_id"],
            "challenge_id": row["challenge_id"],
            "submission_id": row["submission_id"],
            "submission_version": row["submission_version"],
            "commitment": row["commitment"],
            "criteria_hash": row["criteria_hash"],
            "verdict": row["decision"],
            "policy": {"id": row["policy_id"], "version": row["policy_version"]},
            "reason": row["reason"],
            "signature": row["signature"],
            "verifier": row["verifier_subject"],
            "verifier_key_fingerprint": row["verifier_key_fingerprint"],
            "verification_source": "configured_verifier_policy_decision",
            "issued_at": row["issued_at"],
            "resolved_at": row["resolved_at"],
        }

    @staticmethod
    def _settlement_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "verdict_id": row["verdict_id"],
            "challenge_id": row["challenge_id"],
            "operation": row["operation"],
            "status": row["status"],
            "recipient": row["recipient_subject"],
            "amount": row["amount"],
            "currency": row["currency"],
            "txid": row["txid"],
            "adapter": row["adapter"],
            "network": row["network"],
            "real_funds": False,
            "settled_at": row["settled_at"],
        }

    def create_challenge(
        self,
        principal: Principal,
        payload: ChallengeIn,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        with self.db.transaction() as conn:
            replay = self.db.replay(
                conn,
                operation="create_challenge",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            self._quota(conn, principal)
            now = self._now()
            now_text = iso_utc(now)
            expires_at = iso_utc(payload.expires_at)
            if payload.expires_at <= now:
                raise ServiceError("expires_at must be in the future", status_code=422)
            if payload.expires_at > now + timedelta(
                seconds=self.settings.max_challenge_window_seconds
            ):
                raise ServiceError(
                    "expires_at exceeds the maximum challenge window", status_code=422
                )
            if payload.bounty_amount > self.settings.max_bounty_amount:
                raise ServiceError(
                    "bounty_amount exceeds the configured maximum", status_code=422
                )
            criteria = payload.criteria.model_dump(mode="json")
            criteria_hash = self._criteria_hash(criteria)
            challenge_id = self._new_id()
            brief = self._brief(payload, criteria, expires_at)
            conn.execute(
                """
                INSERT INTO challenges (
                    id, claimant_subject, sponsor_subject, claim_text, category,
                    criteria_json, criteria_hash, brief_json, bounty_amount, currency,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    principal.subject,
                    principal.subject,
                    payload.claim,
                    payload.category,
                    dump_json(criteria),
                    criteria_hash,
                    dump_json(brief),
                    payload.bounty_amount,
                    SIMULATED_CURRENCY,
                    expires_at,
                    now_text,
                ),
            )
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            data = {"challenge": self._challenge_base(row)}
            self.db.remember(
                conn,
                operation="create_challenge",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=challenge_id,
                response_status=201,
                response_json=data,
                created_at=now_text,
            )
            return MutationResult(data=data)

    def get_challenge(self, challenge_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            if row is None:
                raise NotFound("challenge not found")
            remote = conn.execute(
                "SELECT * FROM remote_evidence WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            task = conn.execute(
                "SELECT * FROM field_tasks WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            terminal = conn.execute(
                """
                SELECT 1 FROM verdicts
                WHERE challenge_id = ? AND decision IN ('accepted', 'rejected')
                LIMIT 1
                """,
                (challenge_id,),
            ).fetchone()
        result = self._challenge_base(row)
        result["remote_evidence"] = (
            None if remote is None else self._remote_base(remote)
        )
        result["field_task"] = None if task is None else self._task_base(task)
        now = self._now()
        if terminal is not None:
            state = "resolved"
        elif now >= self._parse_time(row["expires_at"]):
            state = "expired"
        elif remote is None:
            state = "awaiting_remote_evidence"
        elif remote["status"] != "insufficient":
            state = f"remote_{remote['status']}"
        elif task is None:
            state = "awaiting_field_task"
        else:
            state = "field_task_open"
        result["state"] = state
        return result

    def run_remote_evidence(
        self,
        principal: Principal,
        challenge_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        with self.db.transaction() as conn:
            replay = self.db.replay(
                conn,
                operation="remote_evidence",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            self._quota(conn, principal)
            challenge = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise NotFound("challenge not found")
            if principal.subject != challenge["claimant_subject"]:
                raise Conflict(
                    "only the challenge claimant can request remote evidence"
                )
            self._require_not_expired(challenge, self._now())
            evidence_input = RemoteEvidenceInput(
                challenge_id=challenge_id,
                claim=challenge["claim_text"],
                category=challenge["category"],
                criteria_hash=challenge["criteria_hash"],
                expires_at=challenge["expires_at"],
            )
            try:
                remote_result = self.remote_adapter.evaluate(evidence_input)
            except Exception as exc:  # noqa: BLE001 - adapter failures become unavailable
                logger.error("remote_adapter_failed error_type=%s", type(exc).__name__)
                remote_result = RemoteEvidenceResult(
                    status="unavailable",
                    summary="The configured remote-evidence adapter could not complete the check.",
                    provider=getattr(
                        self.remote_adapter, "provider", "configured_adapter"
                    ),
                    provider_version=getattr(
                        self.remote_adapter, "provider_version", "unknown"
                    ),
                    source_label="adapter_error",
                )
            self._require_not_expired(challenge, self._now())
            input_hash = hashlib.sha256(
                dump_json(evidence_input.__dict__).encode("utf-8")
            ).hexdigest()
            existing = conn.execute(
                "SELECT * FROM remote_evidence WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            if existing is not None:
                raise Conflict("remote evidence has already been recorded")
            remote_id = self._new_id()
            checked_at = iso_utc(self._now())
            conn.execute(
                """
                INSERT INTO remote_evidence (
                    id, challenge_id, status, summary, provider, provider_version,
                    source_label, input_hash, is_cryptographic_proof, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    remote_id,
                    challenge_id,
                    remote_result.status,
                    remote_result.summary,
                    remote_result.provider,
                    remote_result.provider_version,
                    remote_result.source_label,
                    input_hash,
                    checked_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM remote_evidence WHERE id = ?", (remote_id,)
            ).fetchone()
            data = {"remote_evidence": self._remote_base(row)}
            self.db.remember(
                conn,
                operation="remote_evidence",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=remote_id,
                response_status=201,
                response_json=data,
                created_at=checked_at,
            )
            return MutationResult(data=data)

    def create_field_task(
        self,
        principal: Principal,
        challenge_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        with self.db.transaction() as conn:
            replay = self.db.replay(
                conn,
                operation="field_task",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            self._quota(conn, principal)
            now = self._now()
            challenge = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise NotFound("challenge not found")
            if principal.subject != challenge["claimant_subject"]:
                raise Conflict("only the challenge claimant can create its field task")
            self._require_not_expired(challenge, now)
            remote = conn.execute(
                "SELECT * FROM remote_evidence WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            if remote is None:
                raise Conflict("remote evidence is required before field-task creation")
            if remote["status"] != "insufficient":
                raise Conflict("field tasks require insufficient remote evidence")
            existing = conn.execute(
                "SELECT * FROM field_tasks WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            if existing is not None:
                raise Conflict("field task already exists")
            criteria = json.loads(challenge["criteria_json"])
            task_id = self._new_id()
            created_at = iso_utc(now)
            conn.execute(
                """
                INSERT INTO field_tasks (
                    id, challenge_id, remote_evidence_id, public_location, radius_m,
                    evidence_requirements_json, reject_if_json, bounty_amount, currency,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    challenge_id,
                    remote["id"],
                    criteria["public_location"],
                    criteria["radius_m"],
                    dump_json(criteria["required_details"]),
                    dump_json(criteria["reject_if"]),
                    challenge["bounty_amount"],
                    challenge["currency"],
                    challenge["expires_at"],
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM field_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            data = {"field_task": self._task_base(row)}
            self.db.remember(
                conn,
                operation="field_task",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=task_id,
                response_status=201,
                response_json=data,
                created_at=created_at,
            )
            return MutationResult(data=data)

    def submit_evidence(
        self,
        principal: Principal,
        challenge_id: str,
        payload: SubmissionIn,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        with self.db.transaction() as conn:
            replay = self.db.replay(
                conn,
                operation="submit_evidence",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            self._quota(conn, principal)
            now = self._now()
            challenge = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise NotFound("challenge not found")
            self._require_not_expired(challenge, now)
            task = conn.execute(
                "SELECT * FROM field_tasks WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            if task is None:
                raise Conflict("an insufficient remote-evidence field task is required")
            terminal = conn.execute(
                """
                SELECT 1 FROM verdicts
                WHERE challenge_id = ? AND decision IN ('accepted', 'rejected')
                LIMIT 1
                """,
                (challenge_id,),
            ).fetchone()
            if terminal is not None:
                raise Conflict("challenge is already resolved")
            metadata = payload.public_metadata.model_dump(mode="json")
            captured_at = self._parse_time(metadata["captured_at"])
            if captured_at < self._parse_time(task["created_at"]):
                raise ServiceError(
                    "captured_at predates field-task authorization", status_code=422
                )
            if captured_at > now or captured_at >= self._parse_time(task["expires_at"]):
                raise ServiceError(
                    "captured_at must be within the task window", status_code=422
                )
            if metadata["public_location"] != task["public_location"]:
                raise ServiceError(
                    "public_location must match the bounded task label", status_code=422
                )
            active = conn.execute(
                """
                SELECT 1 FROM submission_states
                WHERE challenge_id = ? AND observer_subject = ? AND status = 'open'
                """,
                (challenge_id, principal.subject),
            ).fetchone()
            if active is not None:
                raise Conflict(
                    "observer already has an active submission for this challenge"
                )
            submission_id = self._new_id()
            submitted_at = iso_utc(now)
            commitment = payload.commitment.lower()
            conn.execute(
                """
                INSERT INTO submissions (
                    id, challenge_id, task_id, observer_subject, commitment,
                    public_metadata_json, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    challenge_id,
                    task["id"],
                    principal.subject,
                    commitment,
                    dump_json(metadata),
                    submitted_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO submission_states (
                    submission_id, challenge_id, observer_subject, status, version, updated_at
                ) VALUES (?, ?, ?, 'open', 1, ?)
                """,
                (submission_id, challenge_id, principal.subject, submitted_at),
            )
            row = conn.execute(
                """
                SELECT s.*, ss.status FROM submissions s
                JOIN submission_states ss ON ss.submission_id = s.id
                WHERE s.id = ?
                """,
                (submission_id,),
            ).fetchone()
            data = {"submission": self._submission_base(row)}
            self.db.remember(
                conn,
                operation="submit_evidence",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=submission_id,
                response_status=201,
                response_json=data,
                created_at=submitted_at,
            )
            return MutationResult(data=data)

    def get_submission(
        self, principal: Principal, submission_id: str
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, ss.status FROM submissions s
                JOIN submission_states ss ON ss.submission_id = s.id
                WHERE s.id = ?
                """,
                (submission_id,),
            ).fetchone()
            if row is None:
                raise NotFound("submission not found")
            challenge = conn.execute(
                "SELECT claimant_subject FROM challenges WHERE id = ?",
                (row["challenge_id"],),
            ).fetchone()
        allowed = (
            principal.role in {"verifier", "settlement"}
            or (
                principal.role == "observer"
                and principal.subject == row["observer_subject"]
            )
            or (
                principal.role == "claimant"
                and principal.subject == challenge["claimant_subject"]
            )
        )
        if not allowed:
            raise Forbidden("caller cannot read this submission")
        return self._submission_base(row)

    def record_verdict(
        self,
        principal: Principal,
        payload: VerdictIn,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        failure: _VerdictRejected | None = None
        try:
            with self.db.transaction() as conn:
                replay = self.db.replay(
                    conn,
                    operation="resolve",
                    subject=principal.subject,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replay is not None:
                    return replay
                self._quota(conn, principal)
                row = conn.execute(
                    """
                    SELECT s.*, ss.status, ss.version AS state_version
                    FROM submissions s
                    JOIN submission_states ss ON ss.submission_id = s.id
                    WHERE s.id = ?
                    """,
                    (str(payload.submission_id),),
                ).fetchone()
                if row is None:
                    raise NotFound("submission not found")
                challenge = conn.execute(
                    "SELECT * FROM challenges WHERE id = ?", (row["challenge_id"],)
                ).fetchone()
                now = self._now()
                if str(payload.challenge_id) != row["challenge_id"]:
                    raise _VerdictRejected(
                        Conflict("verdict challenge binding does not match"),
                        "binding_mismatch",
                        "challenge binding mismatch",
                    )
                if payload.commitment.lower() != row["commitment"]:
                    raise _VerdictRejected(
                        Conflict("verdict commitment binding does not match"),
                        "binding_mismatch",
                        "commitment binding mismatch",
                    )
                if payload.criteria_hash.lower() != challenge["criteria_hash"]:
                    raise _VerdictRejected(
                        Conflict("verdict criteria binding does not match"),
                        "binding_mismatch",
                        "criteria binding mismatch",
                    )
                if payload.submission_version != row["version"]:
                    raise _VerdictRejected(
                        Conflict("submission version is stale"),
                        "stale_version",
                        "submission version mismatch",
                    )
                if not verify_verdict_signature(
                    self.settings.verifier_public_key,
                    payload.model_dump(),
                    payload.signature,
                ):
                    raise _VerdictRejected(
                        InvalidSignature("verifier signature is invalid"),
                        "invalid_signature",
                        "Ed25519 signature did not verify",
                    )
                issued = payload.issued_at.astimezone(timezone.utc)
                if issued > now + timedelta(minutes=5) or issued < now - timedelta(
                    hours=1
                ):
                    raise _VerdictRejected(
                        ServiceError(
                            "issued_at is outside the accepted clock window",
                            status_code=422,
                        ),
                        "invalid_timestamp",
                        "issued_at outside accepted clock window",
                    )
                existing = conn.execute(
                    "SELECT * FROM verdicts WHERE submission_id = ?", (row["id"],)
                ).fetchone()
                if existing is not None:
                    raise _VerdictRejected(
                        Conflict("submission already has a resolution"),
                        "already_resolved",
                        "one resolution per submission",
                    )
                duplicate_id = conn.execute(
                    "SELECT submission_id FROM verdicts WHERE verdict_id = ?",
                    (str(payload.verdict_id),),
                ).fetchone()
                if duplicate_id is not None:
                    raise _VerdictRejected(
                        Conflict("verdict_id was already used"),
                        "already_resolved",
                        "duplicate verdict_id",
                    )
                terminal = conn.execute(
                    """
                    SELECT id FROM verdicts
                    WHERE challenge_id = ? AND decision IN ('accepted', 'rejected')
                    LIMIT 1
                    """,
                    (row["challenge_id"],),
                ).fetchone()
                if terminal is not None:
                    raise _VerdictRejected(
                        Conflict("challenge already has a terminal verdict"),
                        "challenge_closed",
                        "challenge is closed",
                    )
                verdict_id = self._new_id()
                resolved_at = iso_utc(now)
                signed_payload = canonical_verdict_payload(payload.model_dump())
                conn.execute(
                    """
                    INSERT INTO verdicts (
                        id, verdict_id, submission_id, challenge_id, submission_version,
                        commitment, criteria_hash, decision, policy_id, policy_version,
                        reason, signed_payload_json, signature, verifier_subject,
                        verifier_key_fingerprint, issued_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        verdict_id,
                        str(payload.verdict_id),
                        row["id"],
                        row["challenge_id"],
                        row["version"],
                        row["commitment"],
                        challenge["criteria_hash"],
                        payload.verdict,
                        payload.policy_id,
                        payload.policy_version,
                        payload.reason,
                        dump_json(signed_payload),
                        payload.signature.lower(),
                        principal.subject,
                        self.settings.verifier_key_fingerprint,
                        iso_utc(issued),
                        resolved_at,
                    ),
                )
                updated = conn.execute(
                    """
                    UPDATE submission_states
                    SET status = 'resolved', version = version + 1,
                        verdict_id = ?, updated_at = ?
                    WHERE submission_id = ? AND status = 'open' AND version = ?
                    """,
                    (verdict_id, resolved_at, row["id"], row["state_version"]),
                )
                if updated.rowcount != 1:
                    raise _VerdictRejected(
                        Conflict("submission state changed concurrently"),
                        "stale_version",
                        "compare-and-swap failed",
                    )
                conn.execute(
                    """
                    INSERT INTO verification_attempts (
                        subject, idempotency_key, request_hash, challenge_id,
                        submission_id, submission_version, verdict_id, outcome,
                        reason, attempted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?)
                    """,
                    (
                        principal.subject,
                        idempotency_key,
                        request_hash,
                        row["challenge_id"],
                        row["id"],
                        row["version"],
                        str(payload.verdict_id),
                        "resolution applied",
                        resolved_at,
                    ),
                )
                verdict_row = conn.execute(
                    "SELECT * FROM verdicts WHERE id = ?", (verdict_id,)
                ).fetchone()
                data = {"verdict": self._verdict_base(verdict_row)}
                self.db.remember(
                    conn,
                    operation="resolve",
                    subject=principal.subject,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=verdict_id,
                    response_status=201,
                    response_json=data,
                    created_at=resolved_at,
                )
                return MutationResult(data=data)
        except _VerdictRejected as rejected:
            failure = rejected
        if failure is not None:
            # Failed verification is useful audit history, but it must survive
            # the rollback of the attempted resolution.
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO verification_attempts (
                        subject, idempotency_key, request_hash, challenge_id,
                        submission_id, submission_version, verdict_id, outcome,
                        reason, attempted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        principal.subject,
                        idempotency_key,
                        request_hash,
                        str(payload.challenge_id),
                        str(payload.submission_id),
                        payload.submission_version,
                        str(payload.verdict_id),
                        failure.outcome,
                        failure.reason,
                        iso_utc(self._now()),
                    ),
                )
            raise failure.error
        raise RuntimeError("unreachable verdict state")

    def settle(
        self,
        principal: Principal,
        verdict_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult:
        with self.db.transaction() as conn:
            replay = self.db.replay(
                conn,
                operation="settlement",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay
            self._quota(conn, principal)
            now = self._now()
            verdict = conn.execute(
                "SELECT * FROM verdicts WHERE id = ?", (verdict_id,)
            ).fetchone()
            if verdict is None:
                raise NotFound("verdict not found")
            existing = conn.execute(
                "SELECT * FROM settlements WHERE verdict_id = ?", (verdict_id,)
            ).fetchone()
            if existing is not None:
                raise Conflict("verdict already has a settlement")
            submission = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (verdict["submission_id"],)
            ).fetchone()
            challenge = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (verdict["challenge_id"],)
            ).fetchone()
            if verdict["decision"] == "accepted":
                operation = "payout"
                amount = challenge["bounty_amount"]
                recipient = submission["observer_subject"]
            elif verdict["decision"] == "rejected":
                operation = "refund"
                amount = challenge["bounty_amount"]
                recipient = challenge["sponsor_subject"]
            else:
                operation = "no_payout"
                amount = 0
                recipient = "none"
            settlement_id = self._new_id()
            adapter_result = self.settlement_adapter.settle(
                SettlementRequest(
                    settlement_id=settlement_id,
                    challenge_id=verdict["challenge_id"],
                    verdict_id=verdict_id,
                    operation=operation,
                    amount=amount,
                    currency=challenge["currency"],
                    recipient=recipient,
                )
            )
            if (
                adapter_result.real_funds
                or adapter_result.network != "simulated_testnet"
            ):
                raise ServiceError(
                    "settlement adapter violated the simulation boundary",
                    status_code=502,
                )
            if adapter_result.amount != amount:
                raise ServiceError(
                    "settlement adapter returned the wrong amount", status_code=502
                )
            if adapter_result.currency != challenge["currency"]:
                raise ServiceError(
                    "settlement adapter returned the wrong currency", status_code=502
                )
            if operation == "no_payout":
                if (
                    adapter_result.status != "no_payout"
                    or adapter_result.txid is not None
                ):
                    raise ServiceError(
                        "settlement adapter returned a payout for a no-payout verdict",
                        status_code=502,
                    )
            elif (
                adapter_result.status != "settled"
                or not isinstance(adapter_result.txid, str)
                or not adapter_result.txid
            ):
                raise ServiceError(
                    "settlement adapter did not return a settled transaction",
                    status_code=502,
                )
            settled_at = iso_utc(now)
            conn.execute(
                """
                INSERT INTO settlements (
                    id, verdict_id, challenge_id, operation, status, recipient_subject,
                    amount, currency, txid, adapter, network, real_funds, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    settlement_id,
                    verdict_id,
                    verdict["challenge_id"],
                    operation,
                    adapter_result.status,
                    recipient,
                    adapter_result.amount,
                    adapter_result.currency,
                    adapter_result.txid,
                    self.settlement_adapter.name,
                    adapter_result.network,
                    settled_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM settlements WHERE id = ?", (settlement_id,)
            ).fetchone()
            data = {"settlement": self._settlement_base(row)}
            self.db.remember(
                conn,
                operation="settlement",
                subject=principal.subject,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=settlement_id,
                response_status=201,
                response_json=data,
                created_at=settled_at,
            )
            return MutationResult(data=data)

    def public_receipt(self, challenge_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            challenge = conn.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise NotFound("challenge not found")
            verdict = conn.execute(
                """
                SELECT * FROM verdicts WHERE challenge_id = ?
                ORDER BY resolved_at DESC, rowid DESC LIMIT 1
                """,
                (challenge_id,),
            ).fetchone()
            if verdict is None:
                raise NotFound("public receipt is not available")
            submission = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (verdict["submission_id"],)
            ).fetchone()
            remote = conn.execute(
                "SELECT * FROM remote_evidence WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            task = conn.execute(
                "SELECT * FROM field_tasks WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
            settlement = conn.execute(
                "SELECT * FROM settlements WHERE verdict_id = ?", (verdict["id"],)
            ).fetchone()
        challenge_data = self._challenge_base(challenge)
        remote_data = self._remote_base(remote)
        verdict_data = self._verdict_base(verdict)
        settlement_data = (
            self._settlement_base(settlement)
            if settlement is not None
            else {
                "status": "pending",
                "operation": None,
                "recipient": None,
                "amount": None,
                "currency": challenge["currency"],
                "txid": None,
                "adapter": None,
                "network": "simulated_testnet",
                "real_funds": False,
                "settled_at": None,
            }
        )
        status = (
            "awaiting_settlement"
            if settlement is None
            else (
                "complete_no_payout"
                if settlement["status"] == "no_payout"
                else "complete"
            )
        )
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": f"rr_{challenge_id}",
            "status": status,
            "challenge": challenge_data,
            "criteria_hash": challenge["criteria_hash"],
            "remote_evidence": remote_data,
            "field_evidence": {
                "state": "sealed_record",
                "submission_id": submission["id"],
                "commitment": submission["commitment"],
                "observer": submission["observer_subject"],
                "source_label": "sealed_record_commitment_only",
                "raw_observation_received": False,
                "commitment_verified_against_raw_record": False,
            },
            "verdict": verdict_data,
            "settlement": settlement_data,
            "timestamps": {
                "challenge_created_at": challenge["created_at"],
                "remote_checked_at": remote["checked_at"],
                "field_task_created_at": task["created_at"],
                "submission_created_at": submission["submitted_at"],
                "verdict_issued_at": verdict["issued_at"],
                "verdict_resolved_at": verdict["resolved_at"],
                "settlement_created_at": None
                if settlement is None
                else settlement["settled_at"],
            },
            "verification_sources": {
                "remote_evidence": remote["source_label"],
                "field_evidence": "sealed_record_commitment_only",
                "verdict": "configured_verifier_policy_decision",
                "settlement": None if settlement is None else settlement["adapter"],
            },
            "limitations": [
                "Remote evidence is contextual and is never cryptographic proof.",
                "The service stores a commitment, not the raw observation, and does not verify it against raw bytes.",
                "A verifier applies an explicit policy and may be wrong.",
                "Settlement is a deterministic simulator: no real funds, chain transaction, QIE or mainnet integration.",
            ],
        }
