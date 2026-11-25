"""Additive SQLite schema, immutable audit rows, idempotency and fixed-window quotas."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.errors import IdempotencyConflict, QuotaExceeded
from app.signing import dump_json

SCHEMA_VERSION = 3

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    claimant_subject TEXT NOT NULL,
    sponsor_subject TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    category TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    criteria_hash TEXT NOT NULL CHECK (length(criteria_hash) = 64),
    brief_json TEXT NOT NULL,
    bounty_amount INTEGER NOT NULL CHECK (bounty_amount > 0),
    currency TEXT NOT NULL CHECK (currency IN ('SIMULATED_TESTNET_CREDITS', 'QIE')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version = 1)
);

CREATE TABLE IF NOT EXISTS remote_evidence (
    id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(id),
    status TEXT NOT NULL CHECK (status IN ('likely', 'unlikely', 'insufficient', 'unavailable')),
    summary TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    source_label TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (length(input_hash) = 64),
    is_cryptographic_proof INTEGER NOT NULL CHECK (is_cryptographic_proof = 0),
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field_tasks (
    id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(id),
    remote_evidence_id TEXT NOT NULL UNIQUE REFERENCES remote_evidence(id),
    public_location TEXT NOT NULL,
    radius_m INTEGER NOT NULL CHECK (radius_m BETWEEN 1 AND 1000),
    evidence_requirements_json TEXT NOT NULL,
    reject_if_json TEXT NOT NULL,
    bounty_amount INTEGER NOT NULL CHECK (bounty_amount > 0),
    currency TEXT NOT NULL CHECK (currency IN ('SIMULATED_TESTNET_CREDITS', 'QIE')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version = 1)
);

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL REFERENCES challenges(id),
    task_id TEXT NOT NULL REFERENCES field_tasks(id),
    observer_subject TEXT NOT NULL,
    commitment TEXT NOT NULL CHECK (length(commitment) = 64),
    public_metadata_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version = 1)
);

CREATE TABLE IF NOT EXISTS submission_states (
    submission_id TEXT PRIMARY KEY REFERENCES submissions(id),
    challenge_id TEXT NOT NULL REFERENCES challenges(id),
    observer_subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    version INTEGER NOT NULL CHECK (version >= 1),
    verdict_id TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_submission_per_observer
    ON submission_states(challenge_id, observer_subject) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS verdicts (
    id TEXT PRIMARY KEY,
    verdict_id TEXT NOT NULL UNIQUE,
    submission_id TEXT NOT NULL UNIQUE REFERENCES submissions(id),
    challenge_id TEXT NOT NULL REFERENCES challenges(id),
    submission_version INTEGER NOT NULL CHECK (submission_version = 1),
    commitment TEXT NOT NULL CHECK (length(commitment) = 64),
    criteria_hash TEXT NOT NULL CHECK (length(criteria_hash) = 64),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected', 'needs_witness', 'cannot_determine')),
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version > 0),
    reason TEXT NOT NULL,
    signed_payload_json TEXT NOT NULL,
    signature TEXT NOT NULL CHECK (length(signature) = 128),
    verifier_subject TEXT NOT NULL,
    verifier_key_fingerprint TEXT NOT NULL CHECK (length(verifier_key_fingerprint) = 64),
    issued_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    verdict_id TEXT NOT NULL UNIQUE REFERENCES verdicts(id),
    challenge_id TEXT NOT NULL REFERENCES challenges(id),
    operation TEXT NOT NULL CHECK (operation IN ('payout', 'refund', 'no_payout')),
    status TEXT NOT NULL CHECK (status IN ('settled', 'no_payout')),
    recipient_subject TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount >= 0),
    currency TEXT NOT NULL CHECK (currency IN ('SIMULATED_TESTNET_CREDITS', 'QIE')),
    txid TEXT,
    adapter TEXT NOT NULL,
    network TEXT NOT NULL CHECK (network IN ('simulated_testnet', 'qie_testnet', 'qie_mainnet')),
    real_funds INTEGER NOT NULL CHECK (real_funds IN (0, 1)),
    settled_at TEXT NOT NULL,
    CHECK ((operation = 'no_payout' AND amount = 0 AND txid IS NULL)
        OR (operation IN ('payout', 'refund') AND amount > 0 AND txid IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS verification_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    idempotency_key TEXT,
    request_hash TEXT NOT NULL,
    challenge_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    submission_version INTEGER NOT NULL,
    verdict_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'already_resolved', 'stale_version', 'binding_mismatch', 'invalid_signature', 'invalid_timestamp', 'challenge_closed')),
    reason TEXT NOT NULL,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_submission
    ON verification_attempts(submission_id, attempt_id);

CREATE TABLE IF NOT EXISTS idempotency_records (
    operation TEXT NOT NULL,
    subject TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (operation, subject, idempotency_key)
);

CREATE TABLE IF NOT EXISTS request_usage (
    subject TEXT NOT NULL,
    operation TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0),
    PRIMARY KEY (subject, operation)
);

CREATE TRIGGER IF NOT EXISTS challenges_no_update
BEFORE UPDATE ON challenges BEGIN SELECT RAISE(ABORT, 'challenges are immutable'); END;
CREATE TRIGGER IF NOT EXISTS challenges_no_delete
BEFORE DELETE ON challenges BEGIN SELECT RAISE(ABORT, 'challenges are immutable'); END;
CREATE TRIGGER IF NOT EXISTS remote_evidence_no_update
BEFORE UPDATE ON remote_evidence BEGIN SELECT RAISE(ABORT, 'remote evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS remote_evidence_no_delete
BEFORE DELETE ON remote_evidence BEGIN SELECT RAISE(ABORT, 'remote evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS field_tasks_no_update
BEFORE UPDATE ON field_tasks BEGIN SELECT RAISE(ABORT, 'field tasks are immutable'); END;
CREATE TRIGGER IF NOT EXISTS field_tasks_no_delete
BEFORE DELETE ON field_tasks BEGIN SELECT RAISE(ABORT, 'field tasks are immutable'); END;
CREATE TRIGGER IF NOT EXISTS submissions_no_update
BEFORE UPDATE ON submissions BEGIN SELECT RAISE(ABORT, 'submissions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS submissions_no_delete
BEFORE DELETE ON submissions BEGIN SELECT RAISE(ABORT, 'submissions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_no_update
BEFORE UPDATE ON verdicts BEGIN SELECT RAISE(ABORT, 'verdicts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_no_delete
BEFORE DELETE ON verdicts BEGIN SELECT RAISE(ABORT, 'verdicts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlements_no_update
BEFORE UPDATE ON settlements BEGIN SELECT RAISE(ABORT, 'settlements are immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlements_no_delete
BEFORE DELETE ON settlements BEGIN SELECT RAISE(ABORT, 'settlements are immutable'); END;
CREATE TRIGGER IF NOT EXISTS verification_attempts_no_update
BEFORE UPDATE ON verification_attempts BEGIN SELECT RAISE(ABORT, 'verification attempts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS verification_attempts_no_delete
BEFORE DELETE ON verification_attempts BEGIN SELECT RAISE(ABORT, 'verification attempts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_update
BEFORE UPDATE ON idempotency_records BEGIN SELECT RAISE(ABORT, 'idempotency records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_delete
BEFORE DELETE ON idempotency_records BEGIN SELECT RAISE(ABORT, 'idempotency records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS submission_states_no_delete
BEFORE DELETE ON submission_states BEGIN SELECT RAISE(ABORT, 'submission state history cannot be deleted'); END;
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS principal_request_usage (
    subject TEXT PRIMARY KEY,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0)
);

INSERT INTO principal_request_usage (subject, window_start, count)
SELECT usage.subject, usage.window_start, SUM(usage.count)
FROM request_usage AS usage
JOIN (
    SELECT subject, MAX(window_start) AS latest_window
    FROM request_usage
    GROUP BY subject
) AS latest
    ON usage.subject = latest.subject AND usage.window_start = latest.latest_window
GROUP BY usage.subject, usage.window_start
ON CONFLICT (subject) DO UPDATE SET
    window_start = excluded.window_start,
    count = excluded.count
WHERE excluded.window_start > principal_request_usage.window_start
    OR (
        excluded.window_start = principal_request_usage.window_start
        AND excluded.count > principal_request_usage.count
    );

CREATE TRIGGER IF NOT EXISTS settlements_operation_status
BEFORE INSERT ON settlements
WHEN (NEW.operation = 'no_payout' AND NEW.status != 'no_payout')
    OR (NEW.operation IN ('payout', 'refund') AND NEW.status != 'settled')
BEGIN
    SELECT RAISE(ABORT, 'settlement operation/status mismatch');
END;
"""


SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS chain_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('challenge_created', 'evidence_submitted', 'challenge_resolved')),
    challenge_id TEXT NOT NULL REFERENCES challenges(id),
    submission_id TEXT REFERENCES submissions(id),
    verdict_id TEXT REFERENCES verdicts(id),
    tx_hash TEXT NOT NULL UNIQUE,
    chain_id INTEGER NOT NULL CHECK (chain_id > 0),
    contract_address TEXT NOT NULL,
    sender_address TEXT NOT NULL,
    network TEXT NOT NULL CHECK (network IN ('qie_testnet', 'qie_mainnet')),
    currency TEXT NOT NULL CHECK (currency = 'QIE'),
    amount INTEGER NOT NULL CHECK (amount >= 0),
    payload_json TEXT NOT NULL,
    block_number INTEGER,
    explorer_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chain_events_challenge
    ON chain_events(challenge_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chain_events_submission
    ON chain_events(submission_id);

CREATE TRIGGER IF NOT EXISTS chain_events_no_update
BEFORE UPDATE ON chain_events BEGIN SELECT RAISE(ABORT, 'chain events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS chain_events_no_delete
BEFORE DELETE ON chain_events BEGIN SELECT RAISE(ABORT, 'chain events are immutable'); END;
"""

MIGRATIONS: dict[int, str] = {1: SCHEMA_V1, 2: SCHEMA_V2, 3: SCHEMA_V3}


@dataclass(frozen=True)
class MutationResult:
    data: dict[str, Any]
    status_code: int = 201
    replayed: bool = False


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _migrate(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError("database schema is newer than this service")
            for version in sorted(MIGRATIONS):
                if version <= current:
                    continue
                # Migrations are additive CREATE IF NOT EXISTS statements only. QIE currency
                # support predates deployment; reset unreleased demo databases created with v1/v2.
                conn.executescript(MIGRATIONS[version])
                conn.execute(f"PRAGMA user_version={version}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    @staticmethod
    def replay(
        conn: sqlite3.Connection,
        *,
        operation: str,
        subject: str,
        idempotency_key: str,
        request_hash: str,
    ) -> MutationResult | None:
        row = conn.execute(
            """
            SELECT request_hash, resource_id, response_status, response_json
            FROM idempotency_records
            WHERE operation = ? AND subject = ? AND idempotency_key = ?
            """,
            (operation, subject, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise IdempotencyConflict(
                "idempotency key was already used with a different request"
            )
        return MutationResult(
            data=json.loads(row["response_json"]),
            status_code=int(row["response_status"]),
            replayed=True,
        )

    @staticmethod
    def remember(
        conn: sqlite3.Connection,
        *,
        operation: str,
        subject: str,
        idempotency_key: str,
        request_hash: str,
        resource_id: str,
        response_status: int,
        response_json: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO idempotency_records (
                operation, subject, idempotency_key, request_hash, resource_id,
                response_status, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation,
                subject,
                idempotency_key,
                request_hash,
                resource_id,
                response_status,
                dump_json(response_json),
                created_at,
            ),
        )

    def consume_quota(
        self, *, conn: sqlite3.Connection, subject: str, limit: int, now: datetime
    ) -> None:
        epoch = int(now.timestamp())
        window_start = epoch - (epoch % 3_600)
        row = conn.execute(
            """
            SELECT count FROM principal_request_usage
            WHERE subject = ? AND window_start = ?
            """,
            (subject, window_start),
        ).fetchone()
        count = 0 if row is None else int(row["count"])
        if count >= limit:
            raise QuotaExceeded(window_start + 3_600 - epoch)
        if row is None:
            conn.execute(
                """
                INSERT INTO principal_request_usage (subject, window_start, count)
                VALUES (?, ?, 1)
                ON CONFLICT (subject) DO UPDATE SET
                    window_start = excluded.window_start,
                    count = 1
                """,
                (subject, window_start),
            )
        else:
            conn.execute(
                """
                UPDATE principal_request_usage SET count = count + 1
                WHERE subject = ? AND window_start = ?
                """,
                (subject, window_start),
            )


def utc_now() -> datetime:
    return datetime.now(UTC)
