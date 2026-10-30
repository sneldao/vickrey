"""SQLite store for the verifier-held receipts.

One row per anchored commitment. The commitment -> txid -> height
binding lives ONLY here; it is served exclusively to the holder of the
receipt id. There is deliberately no list-of-receipts query in this
module: the service must not offer an enumeration of what has been
anchored (docs/ZANCHOR_API.md).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id  TEXT PRIMARY KEY,
    commitment  TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL,          -- queued | broadcast | confirmed | failed
    mode        TEXT NOT NULL,          -- A | B
    shielded    INTEGER NOT NULL,       -- 1 | 0
    opid        TEXT,
    txid        TEXT,
    height      INTEGER,
    anchored_at TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disclosure_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    purpose     TEXT NOT NULL
);
"""

STATUS_VALUES = ("queued", "broadcast", "confirmed", "failed")


def new_receipt_id() -> str:
    return "rec_" + uuid.uuid4().hex


class Receipts:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            try:  # databases from before the error column
                self._conn.execute("ALTER TABLE receipts ADD COLUMN error TEXT")
            except sqlite3.OperationalError:
                pass
            self._conn.commit()

    # -- receipts ----------------------------------------------------------

    def insert(
        self,
        commitment: str,
        mode: str,
        shielded: bool,
        opid: str | None,
        txid: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        receipt = {
            "receipt_id": new_receipt_id(),
            "commitment": commitment,
            "status": status,
            "mode": mode,
            "shielded": shielded,
            "opid": opid,
            "txid": txid,
            "height": None,
            "anchored_at": None,
            "created_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO receipts (receipt_id, commitment, status, mode, shielded,"
                " opid, txid, height, anchored_at, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt["receipt_id"],
                    receipt["commitment"],
                    receipt["status"],
                    receipt["mode"],
                    1 if receipt["shielded"] else 0,
                    receipt["opid"],
                    receipt["txid"],
                    None,
                    None,
                    receipt["created_at"],
                ),
            )
            self._conn.commit()
        return receipt

    def get(self, receipt_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
            ).fetchone()
        return _row(row) if row else None

    def by_commitment(self, commitment: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM receipts WHERE commitment = ?", (commitment,)
            ).fetchone()
        return _row(row) if row else None

    def set_broadcast(self, receipt_id: str, txid: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE receipts SET status = 'broadcast', txid = ? WHERE receipt_id = ?",
                (txid, receipt_id),
            )
            self._conn.commit()

    def set_confirmed(self, receipt_id: str, height: int, anchored_at: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE receipts SET status = 'confirmed', height = ?,"
                " anchored_at = ? WHERE receipt_id = ?",
                (height, anchored_at, receipt_id),
            )
            self._conn.commit()

    def set_failed(self, receipt_id: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE receipts SET status = 'failed', error = ? WHERE receipt_id = ?",
                (reason[:200], receipt_id),
            )
            self._conn.commit()

    def delete(self, receipt_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM receipts WHERE receipt_id = ?", (receipt_id,)
            )
            self._conn.commit()

    def unconfirmed(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM receipts WHERE status IN ('queued', 'broadcast')"
            ).fetchall()
        return [_row(r) for r in rows]

    # -- disclosure audit (append-only) --------------------------------------

    def audit_disclosure(self, receipt_id: str, purpose: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO disclosure_audit (receipt_id, created_at, purpose)"
                " VALUES (?,?,?)",
                (receipt_id, _now(), purpose),
            )
            self._conn.commit()

    def disclosure_count(self, receipt_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM disclosure_audit WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return int(row["n"])

    # -- kv (capability cache) ----------------------------------------------

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["shielded"] = bool(out.get("shielded"))
    return out


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
