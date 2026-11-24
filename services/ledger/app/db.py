"""SQLite store for the application evidence copy and the last Hornet read."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.verify import STATUS_VALUES, VerifyResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    block_id_norm TEXT PRIMARY KEY,
    block_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    flow_id TEXT,
    payload_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    solid INTEGER,
    content_match INTEGER,
    milestone_index INTEGER,
    raw_block TEXT,
    ledger_payload_json TEXT,
    ledger_tag TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('VERIFIED', 'PENDING', 'PAYLOAD_MISMATCH', 'NOT_SOLID')
    ),
    verified_at TEXT,
    hornet_status INTEGER,
    detail TEXT,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS idx_messages_tag ON messages(tag);
CREATE INDEX IF NOT EXISTS idx_messages_flow ON messages(flow_id);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_inserted ON messages(inserted_at);

CREATE TABLE IF NOT EXISTS submissions (
    block_id_norm TEXT PRIMARY KEY,
    block_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    flow_id TEXT,
    payload_json TEXT NOT NULL,
    hornet_status INTEGER,
    inserted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_idempotency (
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    block_id_norm TEXT NOT NULL,
    created INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id_norm TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    tag TEXT NOT NULL,
    status TEXT NOT NULL,
    solid INTEGER,
    content_match INTEGER,
    milestone_index INTEGER,
    ledger_tag TEXT,
    detail TEXT,
    applied INTEGER NOT NULL,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_message
    ON verification_attempts(block_id_norm, attempt_id);

CREATE TABLE IF NOT EXISTS request_usage (
    subject TEXT NOT NULL,
    operation TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (subject, operation)
);

CREATE TRIGGER IF NOT EXISTS submissions_no_update
BEFORE UPDATE ON submissions BEGIN
    SELECT RAISE(ABORT, 'submissions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS submissions_no_delete
BEFORE DELETE ON submissions BEGIN
    SELECT RAISE(ABORT, 'submissions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_update
BEFORE UPDATE ON ingest_idempotency BEGIN
    SELECT RAISE(ABORT, 'idempotency records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_delete
BEFORE DELETE ON ingest_idempotency BEGIN
    SELECT RAISE(ABORT, 'idempotency records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS verification_no_update
BEFORE UPDATE ON verification_attempts BEGIN
    SELECT RAISE(ABORT, 'verification attempts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS verification_no_delete
BEFORE DELETE ON verification_attempts BEGIN
    SELECT RAISE(ABORT, 'verification attempts are immutable');
END;
"""


class ApplicationConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


@dataclass(frozen=True)
class SubmissionResult:
    row: dict
    created: bool
    replayed: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalize_block_id(block_id: str) -> str:
    text = block_id.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    return text.lower()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def tri_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def parse_time_bound(value: str, *, end: bool) -> str:
    raw = value.strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        suffix = "T23:59:59.999999Z" if end else "T00:00:00.000000Z"
        return raw + suffix
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(messages)")
            }
            if columns and "version" not in columns:
                conn.execute(
                    "ALTER TABLE messages ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
            conn.executescript(SCHEMA)
            conn.execute(
                """
                INSERT OR IGNORE INTO submissions (
                    block_id_norm, block_id, tag, flow_id, payload_json,
                    hornet_status, inserted_at
                )
                SELECT block_id_norm, block_id, tag, flow_id, payload_json,
                       hornet_status, inserted_at
                FROM messages
                """
            )

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def submit_application(
        self,
        *,
        block_id: str,
        tag: str,
        flow_id: str | None,
        payload: Any,
        hornet_status: int | None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> SubmissionResult:
        norm = normalize_block_id(block_id)
        now = utc_now()
        payload_json = dump_json(payload)
        with self.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                if not request_hash:
                    raise ValueError("idempotency requires a request hash")
                prior = conn.execute(
                    "SELECT * FROM ingest_idempotency WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if prior is not None:
                    if prior["request_hash"] != request_hash:
                        raise IdempotencyConflict(
                            "idempotency key was already used with different bytes"
                        )
                    row = conn.execute(
                        """
                        SELECT m.*, s.payload_json AS submission_payload_json
                        FROM messages m JOIN submissions s USING (block_id_norm)
                        WHERE m.block_id_norm = ?
                        """,
                        (prior["block_id_norm"],),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("idempotency record has no message")
                    return SubmissionResult(dict(row), False, True)

            existing = conn.execute(
                "SELECT * FROM submissions WHERE block_id_norm = ?", (norm,)
            ).fetchone()
            if existing is not None:
                same = (
                    existing["tag"] == tag
                    and existing["flow_id"] == flow_id
                    and existing["payload_json"] == payload_json
                    and existing["hornet_status"] == hornet_status
                )
                if not same:
                    raise ApplicationConflict(
                        "block_id was already submitted with different content"
                    )
                if idempotency_key is not None:
                    conn.execute(
                        """
                        INSERT INTO ingest_idempotency (
                            idempotency_key, request_hash, block_id_norm,
                            created, created_at
                        ) VALUES (?, ?, ?, 0, ?)
                        """,
                        (idempotency_key, request_hash, norm, now),
                    )
                row = conn.execute(
                    """
                    SELECT m.*, s.payload_json AS submission_payload_json
                    FROM messages m JOIN submissions s USING (block_id_norm)
                    WHERE m.block_id_norm = ?
                    """,
                    (norm,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("submission has no message")
                return SubmissionResult(dict(row), False, True)

            conn.execute(
                """
                INSERT INTO messages (
                    block_id_norm, block_id, tag, flow_id, payload_json,
                    inserted_at, status, hornet_status, detail, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, 1)
                """,
                (
                    norm,
                    block_id,
                    tag,
                    flow_id,
                    payload_json,
                    now,
                    hornet_status,
                    "stored, verification not finished",
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO submissions (
                    block_id_norm, block_id, tag, flow_id, payload_json,
                    hornet_status, inserted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (norm, block_id, tag, flow_id, payload_json, hornet_status, now),
            )
            if idempotency_key is not None:
                conn.execute(
                    """
                    INSERT INTO ingest_idempotency (
                        idempotency_key, request_hash, block_id_norm,
                        created, created_at
                    ) VALUES (?, ?, ?, 1, ?)
                    """,
                    (idempotency_key, request_hash, norm, now),
                )
            row = conn.execute(
                """
                SELECT m.*, s.payload_json AS submission_payload_json
                FROM messages m JOIN submissions s USING (block_id_norm)
                WHERE m.block_id_norm = ?
                """,
                (norm,),
            ).fetchone()
            if row is None:
                raise RuntimeError("submission insert did not retain a message")
            return SubmissionResult(dict(row), True)

    def save_verification(
        self,
        block_id: str,
        result: VerifyResult,
        *,
        expected_version: int,
        checked_payload_json: str,
        checked_tag: str,
    ) -> bool:
        norm = normalize_block_id(block_id)
        if result.status not in STATUS_VALUES:
            raise ValueError(f"unknown status {result.status}")
        now = utc_now()
        raw_block = None if result.raw_block is None else dump_json(result.raw_block)
        ledger_payload = (
            None
            if result.ledger_payload is None and result.raw_block is None
            else dump_json(result.ledger_payload)
        )
        if result.raw_block is None:
            ledger_payload = None
        with self.session() as conn:
            current = conn.execute(
                "SELECT version FROM messages WHERE block_id_norm = ?",
                (norm,),
            ).fetchone()
            if current is None:
                raise KeyError(block_id)
            updated = conn.execute(
                """
                UPDATE messages
                SET solid = ?, content_match = ?, milestone_index = ?,
                    raw_block = ?, ledger_payload_json = ?, ledger_tag = ?,
                    status = ?, verified_at = ?, detail = ?, updated_at = ?,
                    version = version + 1
                WHERE block_id_norm = ? AND version = ?
                """,
                (
                    tri_bool(result.solid),
                    tri_bool(result.content_match),
                    result.milestone_index,
                    raw_block,
                    ledger_payload,
                    result.ledger_tag,
                    result.status,
                    now,
                    result.detail,
                    now,
                    norm,
                    expected_version,
                ),
            )
            applied = updated.rowcount == 1
            conn.execute(
                """
                INSERT INTO verification_attempts (
                    block_id_norm, version, payload_json, tag, status, solid,
                    content_match, milestone_index, ledger_tag, detail,
                    applied, attempted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm,
                    expected_version,
                    checked_payload_json,
                    checked_tag,
                    result.status,
                    tri_bool(result.solid),
                    tri_bool(result.content_match),
                    result.milestone_index,
                    result.ledger_tag,
                    result.detail,
                    int(applied),
                    now,
                ),
            )
            return applied

    def update_payload(
        self,
        block_id: str,
        payload: Any,
        *,
        expected_version: int,
    ) -> bool:
        norm = normalize_block_id(block_id)
        with self.session() as conn:
            updated = conn.execute(
                """
                UPDATE messages
                SET payload_json = ?, status = 'PENDING', solid = NULL,
                    content_match = NULL, milestone_index = NULL,
                    verified_at = NULL,
                    detail = 'application copy changed; verification required',
                    updated_at = ?, version = version + 1
                WHERE block_id_norm = ? AND version = ?
                """,
                (dump_json(payload), utc_now(), norm, expected_version),
            )
            return updated.rowcount == 1

    def verification_attempts(self, block_id: str, *, limit: int = 100) -> list[dict]:
        norm = normalize_block_id(block_id)
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM verification_attempts
                WHERE block_id_norm = ? ORDER BY attempt_id DESC LIMIT ?
                """,
                (norm, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def consume_request_limit(
        self,
        *,
        subject: str,
        operation: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        now = int(time.time())
        with self.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT window_start, count FROM request_usage
                WHERE subject = ? AND operation = ?
                """,
                (subject, operation),
            ).fetchone()
            if row is None or now >= row["window_start"] + window_seconds:
                conn.execute(
                    """
                    INSERT INTO request_usage (subject, operation, window_start, count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(subject, operation) DO UPDATE SET
                        window_start = excluded.window_start, count = 1
                    """,
                    (subject, operation, now),
                )
                return True, 0
            if row["count"] >= limit:
                retry_after = row["window_start"] + window_seconds - now
                return False, max(1, retry_after)
            conn.execute(
                """
                UPDATE request_usage SET count = count + 1
                WHERE subject = ? AND operation = ?
                """,
                (subject, operation),
            )
            return True, 0

    def get(self, block_id: str) -> dict | None:
        norm = normalize_block_id(block_id)
        with self.session() as conn:
            row = conn.execute(
                """
                SELECT m.*, s.payload_json AS submission_payload_json
                FROM messages m JOIN submissions s USING (block_id_norm)
                WHERE m.block_id_norm = ?
                """,
                (norm,),
            ).fetchone()
            return dict(row) if row else None

    def list_messages(
        self,
        *,
        block_id: str | None = None,
        tag: str | None = None,
        flow_id: str | None = None,
        status: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        args: list[Any] = []
        if block_id:
            clauses.append("m.block_id_norm = ?")
            args.append(normalize_block_id(block_id))
        if tag is not None:
            clauses.append("m.tag = ?")
            args.append(tag)
        if flow_id is not None:
            clauses.append("m.flow_id = ?")
            args.append(flow_id)
        if status is not None:
            clauses.append("m.status = ?")
            args.append(status)
        if from_ts is not None:
            clauses.append("m.inserted_at >= ?")
            args.append(from_ts)
        if to_ts is not None:
            clauses.append("m.inserted_at <= ?")
            args.append(to_ts)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.session() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM messages m{where}", args
            ).fetchone()["n"]
            rows = conn.execute(
                f"""
                SELECT m.*, s.payload_json AS submission_payload_json
                FROM messages m JOIN submissions s USING (block_id_norm){where}
                ORDER BY m.inserted_at DESC, m.block_id_norm ASC
                LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
            return [dict(row) for row in rows], int(total)
