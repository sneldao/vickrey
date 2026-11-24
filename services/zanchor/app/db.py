"""SQLite store for verifier-held receipts and durable anchor operations.

One row per anchored commitment. In mode B the commitment rides the
transaction's encrypted memo and the receipt is the service's book of
which commitment landed where (receipt id, txid, height); in mode A the
binding exists only in this store. It is served exclusively to the
holder of the receipt id. There is deliberately no list-of-receipts
query in this module: the service must not offer an enumeration of what
has been anchored (docs/ZANCHOR_API.md).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id       TEXT PRIMARY KEY,
    commitment       TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL,
    mode             TEXT NOT NULL,
    shielded         INTEGER NOT NULL,
    opid             TEXT,
    txid             TEXT,
    height           INTEGER,
    anchored_at      TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    worker_id        TEXT,
    submitter_id     TEXT,
    lease_expires_at REAL,
    updated_at       TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS idempotency (
    idempotency_key TEXT PRIMARY KEY,
    request_sha256  TEXT NOT NULL,
    receipt_id      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS anchor_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    worker_id  TEXT,
    opid       TEXT
);
CREATE TABLE IF NOT EXISTS rate_limits (
    scope        TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count        INTEGER NOT NULL,
    PRIMARY KEY (scope)
);
"""

STATUS_VALUES = (
    "submitting",
    "reconciling",
    "queued",
    "broadcast",
    "confirmed",
    "failed",
)
ACTIVE_STATUSES = ("submitting", "reconciling", "queued", "broadcast")

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS receipts_status_insert_guard
BEFORE INSERT ON receipts
WHEN NEW.status NOT IN (
    'submitting', 'reconciling', 'queued', 'broadcast', 'confirmed', 'failed'
)
BEGIN
    SELECT RAISE(ABORT, 'invalid receipt status');
END;
CREATE TRIGGER IF NOT EXISTS receipts_status_update_guard
BEFORE UPDATE OF status ON receipts
WHEN NEW.status NOT IN (
    'submitting', 'reconciling', 'queued', 'broadcast', 'confirmed', 'failed'
)
BEGIN
    SELECT RAISE(ABORT, 'invalid receipt status');
END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_update
BEFORE UPDATE ON idempotency
BEGIN
    SELECT RAISE(ABORT, 'idempotency records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_delete
BEFORE DELETE ON idempotency
BEGIN
    SELECT RAISE(ABORT, 'idempotency records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS idempotency_no_replace
BEFORE INSERT ON idempotency
WHEN EXISTS (SELECT 1 FROM idempotency WHERE idempotency_key=NEW.idempotency_key)
BEGIN
    SELECT RAISE(ABORT, 'idempotency records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS anchor_events_no_update
BEFORE UPDATE ON anchor_events
BEGIN
    SELECT RAISE(ABORT, 'anchor events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS anchor_events_no_delete
BEFORE DELETE ON anchor_events
BEGIN
    SELECT RAISE(ABORT, 'anchor events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS anchor_events_no_replace
BEFORE INSERT ON anchor_events
WHEN EXISTS (SELECT 1 FROM anchor_events WHERE id=NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'anchor events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS disclosure_audit_no_update
BEFORE UPDATE ON disclosure_audit
BEGIN
    SELECT RAISE(ABORT, 'disclosure audit is append-only');
END;
CREATE TRIGGER IF NOT EXISTS disclosure_audit_no_delete
BEFORE DELETE ON disclosure_audit
BEGIN
    SELECT RAISE(ABORT, 'disclosure audit is append-only');
END;
CREATE TRIGGER IF NOT EXISTS disclosure_audit_no_replace
BEFORE INSERT ON disclosure_audit
WHEN EXISTS (SELECT 1 FROM disclosure_audit WHERE id=NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'disclosure audit is append-only');
END;
"""


class IdempotencyConflict(Exception):
    pass


class CommitmentConflict(Exception):
    pass


class AnchorInFlight(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def new_receipt_id() -> str:
    return "rec_" + uuid.uuid4().hex


class Receipts:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout = 30000")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.executescript(TRIGGERS)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS receipts_status_idx ON receipts(status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idempotency_receipt_idx"
                " ON idempotency(receipt_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS anchor_events_receipt_idx"
                " ON anchor_events(receipt_id, id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS disclosure_audit_receipt_idx"
                " ON disclosure_audit(receipt_id, id)"
            )
            self._conn.execute("PRAGMA user_version = 2")
            self._conn.commit()

    def _migrate(self) -> None:
        """Add operation columns without rewriting or dropping old rows."""
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(receipts)")
        }
        additions = {
            "error": "TEXT",
            "worker_id": "TEXT",
            "submitter_id": "TEXT",
            "lease_expires_at": "REAL",
            "updated_at": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE receipts ADD COLUMN {name} {sql_type}")
        self._conn.execute(
            "UPDATE receipts SET updated_at = created_at WHERE updated_at IS NULL"
        )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, target: str) -> None:
        """Consistent online snapshot of the whole store via the SQLite
        backup API (docs/DEPLOY_DEMO.md). The target must not already exist:
        it is created mode 600 and a partial file is removed on failure.
        The snapshot is plaintext sensitive data — receipt ids are bearer
        capabilities — so it must be encrypted before leaving the host."""
        if os.path.exists(target):
            raise FileExistsError("backup target already exists")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        ok = False
        try:
            dest = sqlite3.connect(target)
            try:
                with self._lock:
                    self._conn.backup(dest)
                rows = dest.execute("PRAGMA quick_check").fetchall()
                ok = rows == [("ok",)]
            finally:
                dest.close()
            if not ok:
                raise RuntimeError("snapshot failed integrity check")
        except Exception:
            try:
                os.remove(target)
            except OSError:
                pass
            raise

    # -- receipts and idempotency ------------------------------------------

    def insert(
        self,
        commitment: str,
        mode: str,
        shielded: bool,
        opid: str | None,
        txid: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        """Compatibility helper for imported/legacy receipts.

        The live pipeline uses reserve_anchor(), which creates a submitting
        receipt and its idempotency record before submitting an RPC.
        """
        now = _now()
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
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._write() as conn:
            conn.execute(
                "INSERT INTO receipts (receipt_id, commitment, status, mode, shielded,"
                " opid, txid, height, anchored_at, error, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt["receipt_id"],
                    commitment,
                    status,
                    mode,
                    int(shielded),
                    opid,
                    txid,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            _event(conn, receipt["receipt_id"], "created", opid=opid)
        return receipt

    def reserve_anchor(
        self,
        commitment: str,
        mode: str,
        idempotency_key: str,
        request_sha256: str,
        worker_id: str,
        lease_expires_at: float,
        *,
        quota_limit: int,
        quota_window_seconds: int,
        now: float | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically replay, reserve, or retry one commitment.

        Returns (receipt, replayed). A failed receipt is reused on retry so
        its id and event history survive; a new idempotency key is required
        to authorize another submission.
        """
        timestamp = time.time() if now is None else now
        with self._write() as conn:
            idem = conn.execute(
                "SELECT request_sha256, receipt_id FROM idempotency"
                " WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if idem is not None:
                if idem["request_sha256"] != request_sha256:
                    raise IdempotencyConflict
                receipt = _get_conn(conn, idem["receipt_id"])
                if receipt is None:
                    raise RuntimeError("idempotency record has no receipt")
                return receipt, True

            existing = conn.execute(
                "SELECT * FROM receipts WHERE commitment = ?", (commitment,)
            ).fetchone()
            if existing is not None and existing["status"] != "failed":
                raise CommitmentConflict
            active = conn.execute(
                "SELECT receipt_id FROM receipts WHERE status IN"
                " ('submitting','reconciling','queued','broadcast') LIMIT 1"
            ).fetchone()
            if active is not None:
                raise AnchorInFlight

            _consume_quota(conn, "anchor", timestamp, quota_window_seconds, quota_limit)
            if existing is not None:
                receipt_id = existing["receipt_id"]
                conn.execute(
                    "UPDATE receipts SET status='submitting', mode=?, shielded=0,"
                    " opid=NULL, txid=NULL, height=NULL, anchored_at=NULL, error=NULL,"
                    " worker_id=?, submitter_id=?, lease_expires_at=?, updated_at=?"
                    " WHERE receipt_id=?",
                    (
                        mode,
                        worker_id,
                        worker_id,
                        lease_expires_at,
                        _now(),
                        receipt_id,
                    ),
                )
                event_type = "retry_reserved"
            else:
                receipt_id = new_receipt_id()
                created = _now()
                conn.execute(
                    "INSERT INTO receipts (receipt_id, commitment, status, mode,"
                    " shielded, opid, txid, height, anchored_at, error, created_at,"
                    " worker_id, submitter_id, lease_expires_at, updated_at)"
                    " VALUES (?,?,'submitting',?,0,NULL,NULL,NULL,NULL,NULL,?,?,?,?,?)",
                    (
                        receipt_id,
                        commitment,
                        mode,
                        created,
                        worker_id,
                        worker_id,
                        lease_expires_at,
                        created,
                    ),
                )
                event_type = "submission_reserved"
            conn.execute(
                "INSERT INTO idempotency"
                " (idempotency_key, request_sha256, receipt_id, created_at)"
                " VALUES (?,?,?,?)",
                (idempotency_key, request_sha256, receipt_id, _now()),
            )
            _event(conn, receipt_id, event_type, worker_id=worker_id)
            receipt = _get_conn(conn, receipt_id)
            if receipt is None:
                raise RuntimeError("reserved receipt missing")
            return receipt, False

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

    def idempotency_receipt(
        self, idempotency_key: str, request_sha256: str
    ) -> dict[str, Any] | None:
        """Read-only replay check, safe before node availability checks."""
        with self._lock:
            row = self._conn.execute(
                "SELECT i.request_sha256, r.* FROM idempotency i"
                " JOIN receipts r ON r.receipt_id = i.receipt_id"
                " WHERE i.idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise IdempotencyConflict
        out = dict(row)
        out.pop("request_sha256")
        out["shielded"] = bool(out["shielded"])
        return out

    def record_opid(
        self,
        receipt_id: str,
        submitter_id: str,
        opid: str,
        mode: str,
        shielded: bool,
    ) -> dict[str, Any] | None:
        """Fence in the submitter's RPC result immediately after it returns."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND submitter_id=?"
                " AND opid IS NULL AND status IN ('submitting','reconciling')",
                (receipt_id, submitter_id),
            ).fetchone()
            if row is None:
                return None
            status = "queued" if row["status"] == "submitting" else "reconciling"
            if status == "queued":
                worker_id, lease_expires_at = None, None
            else:
                worker_id, lease_expires_at = row["worker_id"], row["lease_expires_at"]
            conn.execute(
                "UPDATE receipts SET opid=?, mode=?, shielded=?, status=?, worker_id=?,"
                " lease_expires_at=?, error=NULL, updated_at=? WHERE receipt_id=?",
                (
                    opid,
                    mode,
                    int(shielded),
                    status,
                    worker_id,
                    lease_expires_at,
                    _now(),
                    receipt_id,
                ),
            )
            _event(
                conn,
                receipt_id,
                "opid_recorded",
                worker_id=worker_id,
                opid=opid,
            )
            return _get_conn(conn, receipt_id)

    def fail_submission(
        self, receipt_id: str, submitter_id: str, reason: str
    ) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND submitter_id=?"
                " AND opid IS NULL AND status IN ('submitting','reconciling')",
                (receipt_id, submitter_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET status='failed', error=?, worker_id=NULL,"
                " lease_expires_at=NULL, updated_at=? WHERE receipt_id=?",
                (reason[:200], _now(), receipt_id),
            )
            _event(conn, receipt_id, "submission_failed", worker_id=submitter_id)
            return _get_conn(conn, receipt_id)

    def mark_submission_reconciling(
        self, receipt_id: str, submitter_id: str, reason: str
    ) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND submitter_id=?"
                " AND opid IS NULL AND status IN ('submitting','reconciling')",
                (receipt_id, submitter_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET status='reconciling', error=?, worker_id=NULL,"
                " lease_expires_at=NULL, updated_at=? WHERE receipt_id=?",
                (reason[:200], _now(), receipt_id),
            )
            _event(conn, receipt_id, "submission_uncertain", worker_id=submitter_id)
            return _get_conn(conn, receipt_id)

    # -- durable worker leases ---------------------------------------------

    def expire_submitting_leases(self, now: float | None = None) -> int:
        timestamp = time.time() if now is None else now
        with self._write() as conn:
            rows = conn.execute(
                "SELECT receipt_id FROM receipts WHERE status='submitting'"
                " AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                (timestamp,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE receipts SET status='reconciling',"
                    " error='submission lease expired; outcome uncertain',"
                    " worker_id=NULL, lease_expires_at=NULL, updated_at=?"
                    " WHERE receipt_id=?",
                    (_now(), row["receipt_id"]),
                )
                _event(conn, row["receipt_id"], "submission_lease_expired")
            return len(rows)

    def claim_pending(
        self,
        receipt_id: str,
        worker_id: str,
        lease_expires_at: float,
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        timestamp = time.time() if now is None else now
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND status IN"
                " ('queued','broadcast','reconciling') AND"
                " (worker_id IS NULL OR lease_expires_at IS NULL"
                " OR lease_expires_at <= ?)",
                (receipt_id, timestamp),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET worker_id=?, lease_expires_at=?, updated_at=?"
                " WHERE receipt_id=?",
                (worker_id, lease_expires_at, _now(), receipt_id),
            )
            _event(conn, receipt_id, "lease_claimed", worker_id=worker_id)
            return _get_conn(conn, receipt_id)

    def release_lease(self, receipt_id: str, worker_id: str) -> None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT worker_id FROM receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
            if row is None or row["worker_id"] != worker_id:
                return
            conn.execute(
                "UPDATE receipts SET worker_id=NULL, lease_expires_at=NULL, updated_at=?"
                " WHERE receipt_id=?",
                (_now(), receipt_id),
            )
            _event(conn, receipt_id, "lease_released", worker_id=worker_id)

    def set_broadcast(
        self, receipt_id: str, txid: str, worker_id: str
    ) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND worker_id=?"
                " AND status IN ('queued','reconciling')",
                (receipt_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET status='broadcast', txid=?, error=NULL,"
                " worker_id=NULL, lease_expires_at=NULL, updated_at=?"
                " WHERE receipt_id=?",
                (txid, _now(), receipt_id),
            )
            _event(
                conn,
                receipt_id,
                "broadcast",
                worker_id=worker_id,
                opid=row["opid"],
            )
            return _get_conn(conn, receipt_id)

    def set_confirmed(
        self,
        receipt_id: str,
        height: int,
        anchored_at: str | None,
        worker_id: str,
    ) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND worker_id=?"
                " AND status='broadcast'",
                (receipt_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET status='confirmed', height=?, anchored_at=?,"
                " error=NULL, worker_id=NULL, lease_expires_at=NULL, updated_at=?"
                " WHERE receipt_id=?",
                (height, anchored_at, _now(), receipt_id),
            )
            _event(
                conn,
                receipt_id,
                "confirmed",
                worker_id=worker_id,
                opid=row["opid"],
            )
            return _get_conn(conn, receipt_id)

    def set_failed(
        self, receipt_id: str, reason: str, worker_id: str
    ) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND worker_id=?"
                " AND status IN ('queued','reconciling')",
                (receipt_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE receipts SET status='failed', error=?, worker_id=NULL,"
                " lease_expires_at=NULL, updated_at=? WHERE receipt_id=?",
                (reason[:200], _now(), receipt_id),
            )
            _event(
                conn,
                receipt_id,
                "operation_failed",
                worker_id=worker_id,
                opid=row["opid"],
            )
            return _get_conn(conn, receipt_id)

    def mark_pending_reconciling(
        self, receipt_id: str, worker_id: str, reason: str
    ) -> None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM receipts WHERE receipt_id=? AND worker_id=?"
                " AND status IN ('queued','reconciling')",
                (receipt_id, worker_id),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "UPDATE receipts SET status='reconciling', error=?, worker_id=NULL,"
                " lease_expires_at=NULL, updated_at=? WHERE receipt_id=?",
                (reason[:200], _now(), receipt_id),
            )
            _event(
                conn,
                receipt_id,
                "operation_uncertain",
                worker_id=worker_id,
                opid=row["opid"],
            )

    def unconfirmed(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM receipts WHERE status IN"
                " ('submitting','reconciling','queued','broadcast') ORDER BY created_at"
            ).fetchall()
        return [_row(row) for row in rows]

    # -- fixed-window quotas ------------------------------------------------

    def consume_quota(
        self,
        scope: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        with self._write() as conn:
            _consume_quota(conn, scope, timestamp, window_seconds, limit)

    # -- disclosure audit (append-only) --------------------------------------

    def audit_disclosure(self, receipt_id: str, purpose: str) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO disclosure_audit (receipt_id, created_at, purpose)"
                " VALUES (?,?,?)",
                (receipt_id, _now(), purpose),
            )

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


def _get_conn(conn: sqlite3.Connection, receipt_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
    ).fetchone()
    return _row(row) if row else None


def _event(
    conn: sqlite3.Connection,
    receipt_id: str,
    event_type: str,
    *,
    worker_id: str | None = None,
    opid: str | None = None,
) -> None:
    """Store operational facts only, never request or observation contents."""
    conn.execute(
        "INSERT INTO anchor_events"
        " (receipt_id, event_type, created_at, worker_id, opid)"
        " VALUES (?,?,?,?,?)",
        (receipt_id, event_type, _now(), worker_id, opid),
    )


def _consume_quota(
    conn: sqlite3.Connection,
    scope: str,
    now: float,
    window_seconds: int,
    limit: int,
) -> None:
    window_start = int(now)
    row = conn.execute(
        "SELECT window_start, count FROM rate_limits WHERE scope=?", (scope,)
    ).fetchone()
    if row is None or now - row["window_start"] >= window_seconds:
        conn.execute(
            "INSERT INTO rate_limits (scope, window_start, count) VALUES (?,?,1)"
            " ON CONFLICT(scope) DO UPDATE SET window_start=excluded.window_start,"
            " count=1",
            (scope, window_start),
        )
        return
    if row["count"] >= limit:
        raise QuotaExceeded
    conn.execute("UPDATE rate_limits SET count=count+1 WHERE scope=?", (scope,))


def _row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["shielded"] = bool(out.get("shielded"))
    return out


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
