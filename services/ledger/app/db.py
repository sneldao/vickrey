"""SQLite store for the application evidence copy and the last Hornet read."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
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
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_tag ON messages(tag);
CREATE INDEX IF NOT EXISTS idx_messages_flow ON messages(flow_id);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_inserted ON messages(inserted_at);
"""


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
            conn.executescript(SCHEMA)

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

    def upsert_application(
        self,
        *,
        block_id: str,
        tag: str,
        flow_id: str | None,
        payload: Any,
        hornet_status: int | None,
    ) -> bool:
        norm = normalize_block_id(block_id)
        now = utc_now()
        payload_json = dump_json(payload)
        with self.session() as conn:
            existing = conn.execute(
                "SELECT block_id_norm FROM messages WHERE block_id_norm = ?",
                (norm,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO messages (
                        block_id_norm, block_id, tag, flow_id, payload_json,
                        inserted_at, status, hornet_status, detail, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
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
                return True
            conn.execute(
                """
                UPDATE messages
                SET block_id = ?, tag = ?, flow_id = ?, payload_json = ?,
                    hornet_status = ?, updated_at = ?
                WHERE block_id_norm = ?
                """,
                (block_id, tag, flow_id, payload_json, hornet_status, now, norm),
            )
            return False

    def save_verification(self, block_id: str, result: VerifyResult) -> None:
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
        # A decoded JSON null is stored as the text "null" because raw_block is set.
        # When the block was not fetched, ledger_payload stays SQL NULL.
        if result.raw_block is None:
            ledger_payload = None
        with self.session() as conn:
            updated = conn.execute(
                """
                UPDATE messages
                SET solid = ?, content_match = ?, milestone_index = ?,
                    raw_block = ?, ledger_payload_json = ?, ledger_tag = ?,
                    status = ?, verified_at = ?, detail = ?, updated_at = ?
                WHERE block_id_norm = ?
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
                ),
            )
            if updated.rowcount != 1:
                raise KeyError(block_id)

    def update_payload(self, block_id: str, payload: Any) -> None:
        norm = normalize_block_id(block_id)
        with self.session() as conn:
            updated = conn.execute(
                """
                UPDATE messages
                SET payload_json = ?, updated_at = ?
                WHERE block_id_norm = ?
                """,
                (dump_json(payload), utc_now(), norm),
            )
            if updated.rowcount != 1:
                raise KeyError(block_id)

    def get(self, block_id: str) -> dict | None:
        norm = normalize_block_id(block_id)
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE block_id_norm = ?",
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
            clauses.append("block_id_norm = ?")
            args.append(normalize_block_id(block_id))
        if tag is not None:
            clauses.append("tag = ?")
            args.append(tag)
        if flow_id is not None:
            clauses.append("flow_id = ?")
            args.append(flow_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        if from_ts is not None:
            clauses.append("inserted_at >= ?")
            args.append(from_ts)
        if to_ts is not None:
            clauses.append("inserted_at <= ?")
            args.append(to_ts)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.session() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM messages{where}", args
            ).fetchone()["n"]
            rows = conn.execute(
                f"""
                SELECT * FROM messages{where}
                ORDER BY inserted_at DESC, block_id ASC
                LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
            return [dict(row) for row in rows], int(total)
