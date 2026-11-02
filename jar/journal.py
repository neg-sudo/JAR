"""SQLite journal: history, statistics and undo bookkeeping."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    started REAL NOT NULL,
    finished REAL,
    mode TEXT NOT NULL DEFAULT 'organize',
    dry_run INTEGER NOT NULL DEFAULT 0,
    profile TEXT NOT NULL DEFAULT 'default',
    note TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    moved INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    ts REAL NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    src TEXT NOT NULL,
    dst TEXT,
    category TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    ext TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    undone INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_operations_batch ON operations(batch_id);
CREATE INDEX IF NOT EXISTS idx_operations_ts ON operations(ts);
CREATE INDEX IF NOT EXISTS idx_operations_action ON operations(action);
CREATE INDEX IF NOT EXISTS idx_operations_undone ON operations(undone);

PRAGMA user_version = 2;
"""

UNDOABLE_ACTIONS = ("move", "trash", "quarantine")


class Journal:
    """A small, thread-safe SQLite journal.

    Every mutating action is recorded so it can be reviewed, exported and
    undone.  Quarantined files are recorded separately so an undo restores both
    the moved file and anything it replaced.
    """

    def __init__(self, db_path: Path | str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # --------------------------------------------------------------- batches
    def start_batch(
        self,
        *,
        mode: str = "organize",
        dry_run: bool = False,
        profile: str = "default",
        note: str = "",
        total: int = 0,
    ) -> str:
        batch_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._conn.execute(
                "INSERT INTO batches (id, started, mode, dry_run, profile, note, total) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (batch_id, time.time(), mode, int(bool(dry_run)), profile, note, int(total)),
            )
            self._conn.commit()
        return batch_id

    def finish_batch(
        self,
        batch_id: str,
        *,
        moved: int = 0,
        skipped: int = 0,
        failed: int = 0,
        total: int | None = None,
    ) -> None:
        with self._lock:
            if total is None:
                self._conn.execute(
                    "UPDATE batches SET finished=?, moved=?, skipped=?, failed=? WHERE id=?",
                    (time.time(), int(moved), int(skipped), int(failed), batch_id),
                )
            else:
                self._conn.execute(
                    "UPDATE batches SET finished=?, moved=?, skipped=?, failed=?, total=? WHERE id=?",
                    (time.time(), int(moved), int(skipped), int(failed), int(total), batch_id),
                )
            self._conn.commit()

    # ------------------------------------------------------------- operations
    def record(
        self,
        batch_id: str,
        action: str,
        src: Path | str,
        dst: Path | str | None = None,
        *,
        category: str = "",
        size: int = 0,
        digest: str = "",
        status: str = "ok",
        error: str = "",
    ) -> int:
        src_path = Path(src)
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO operations "
                "(batch_id, ts, action, status, src, dst, category, size, ext, digest, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    time.time(),
                    action,
                    status,
                    str(src_path),
                    str(dst) if dst is not None else None,
                    category,
                    int(size or 0),
                    src_path.suffix.lower().lstrip("."),
                    digest,
                    error,
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)

    def mark_undone(self, operation_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE operations SET undone=1 WHERE id=?", (int(operation_id),))
            self._conn.commit()

    # ------------------------------------------------------------------ read
    def batches(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM batches ORDER BY started DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None

    def operations(
        self,
        *,
        limit: int = 50,
        batch_id: str | None = None,
        status: str | None = None,
        action: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if batch_id:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if search:
            clauses.append("(src LIKE ? OR dst LIKE ? OR category LIKE ? OR error LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM operations {where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        return [dict(row) for row in rows]

    def undo_candidates(
        self, *, count: int = 1, batch_id: str | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (batches, operations) eligible for undo, newest first."""
        with self._lock:
            if batch_id:
                batch_rows = self._conn.execute(
                    "SELECT * FROM batches WHERE id=?", (batch_id,)
                ).fetchall()
            else:
                batch_rows = self._conn.execute(
                    "SELECT b.* FROM batches b WHERE b.mode != 'undo' AND EXISTS ("
                    "  SELECT 1 FROM operations o WHERE o.batch_id=b.id AND o.undone=0 "
                    "  AND o.status='ok' AND o.action IN ('move','trash','quarantine')"
                    ") ORDER BY b.started DESC LIMIT ?",
                    (max(1, int(count)),),
                ).fetchall()
            batches = [dict(row) for row in batch_rows]
            ids = [row["id"] for row in batches]
            if not ids:
                return [], []
            placeholders = ",".join("?" for _ in ids)
            operation_rows = self._conn.execute(
                f"SELECT * FROM operations WHERE batch_id IN ({placeholders}) "
                "AND undone=0 AND status='ok' "
                "AND action IN ('move','trash','quarantine') ORDER BY id DESC",
                ids,
            ).fetchall()
        return batches, [dict(row) for row in operation_rows]

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.operations(limit=limit, search=query)

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict[str, Any]:
        with self._lock:
            def scalar(sql: str, params: tuple = ()) -> Any:
                row = self._conn.execute(sql, params).fetchone()
                return row[0] if row else 0

            def rows(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
                return self._conn.execute(sql, params).fetchall()

            total_operations = scalar("SELECT COUNT(*) FROM operations")
            total_batches = scalar("SELECT COUNT(*) FROM batches")
            moved = scalar(
                "SELECT COUNT(*) FROM operations WHERE action='move' AND status='ok'"
            )
            restored = scalar(
                "SELECT COUNT(*) FROM operations WHERE action='restore' AND status='ok'"
            )
            trashed = scalar(
                "SELECT COUNT(*) FROM operations WHERE action IN ('trash','delete','quarantine') "
                "AND status='ok'"
            )
            skipped = scalar("SELECT COUNT(*) FROM operations WHERE status='skipped'")
            failed = scalar("SELECT COUNT(*) FROM operations WHERE status='error'")
            bytes_moved = scalar(
                "SELECT COALESCE(SUM(size),0) FROM operations WHERE action='move' AND status='ok'"
            )
            bytes_reclaimed = scalar(
                "SELECT COALESCE(SUM(size),0) FROM operations "
                "WHERE action IN ('trash','delete') AND status='ok'"
            )
            first_ts = scalar("SELECT MIN(ts) FROM operations")
            last_ts = scalar("SELECT MAX(ts) FROM operations")

            by_category = [
                {
                    "category": row["category"] or "Others",
                    "count": row["count"],
                    "bytes": row["bytes"] or 0,
                }
                for row in rows(
                    "SELECT category, COUNT(*) AS count, SUM(size) AS bytes FROM operations "
                    "WHERE status='ok' AND action IN ('move','trash','delete') "
                    "GROUP BY category ORDER BY count DESC"
                )
            ]
            by_extension = [
                {
                    "extension": row["ext"] or "none",
                    "count": row["count"],
                    "bytes": row["bytes"] or 0,
                }
                for row in rows(
                    "SELECT ext, COUNT(*) AS count, SUM(size) AS bytes FROM operations "
                    "WHERE status='ok' AND action='move' GROUP BY ext "
                    "ORDER BY count DESC LIMIT 25"
                )
            ]
            by_action = [
                {"action": row["action"], "count": row["count"]}
                for row in rows(
                    "SELECT action, COUNT(*) AS count FROM operations GROUP BY action "
                    "ORDER BY count DESC"
                )
            ]

            today = time.time()
            days: list[dict[str, Any]] = []
            for offset in range(6, -1, -1):
                start = today - offset * 86400
                day_label = time.strftime("%Y-%m-%d", time.localtime(start))
                count, size = self._conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size),0) FROM operations "
                    "WHERE status='ok' AND action='move' AND date(ts,'unixepoch','localtime')=?",
                    (day_label,),
                ).fetchone()
                days.append({"date": day_label, "count": count, "bytes": size or 0})

        try:
            db_bytes = self.path.stat().st_size
        except OSError:
            db_bytes = 0

        return {
            "generated_at": time.time(),
            "db_file": str(self.path),
            "db_bytes": db_bytes,
            "operations": total_operations,
            "batches": total_batches,
            "moved": moved,
            "restored": restored,
            "trashed": trashed,
            "skipped": skipped,
            "failed": failed,
            "bytes_moved": bytes_moved,
            "bytes_reclaimed": bytes_reclaimed,
            "first_activity": first_ts or None,
            "last_activity": last_ts or None,
            "by_category": by_category,
            "by_extension": by_extension,
            "by_action": by_action,
            "last_7_days": days,
        }

    # ----------------------------------------------------------------- write
    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM operations")
            self._conn.execute("DELETE FROM batches")
            self._conn.commit()

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
