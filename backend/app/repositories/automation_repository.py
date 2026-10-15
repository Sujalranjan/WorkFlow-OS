"""SQLite persistence for email triggers and workflow runs.

The workflow_runs table doubles as the processed-email ledger: UNIQUE(trigger_id, message_id)
guarantees one run per message per trigger, across restarts and concurrent polls.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, Iterable, List, Optional

from app.config import DATABASE_PATH
from app.models.automation import EmailTrigger, RunStatus, WorkflowRun


class AutomationRepository:
    """Manages SQLite persistence for EmailTrigger and WorkflowRun records."""

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        self.db_path = db_path
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._memory_conn is not None:
            yield self._memory_conn
        else:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS email_triggers (
                        trigger_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        record_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_runs (
                        run_id TEXT PRIMARY KEY,
                        trigger_id TEXT NOT NULL,
                        workflow_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        record_json TEXT NOT NULL,
                        UNIQUE (trigger_id, message_id)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status)")

    # ------------------------------------------------------------------ triggers

    def save_trigger(self, trigger: EmailTrigger) -> EmailTrigger:
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO email_triggers (trigger_id, workflow_id, enabled, created_at, record_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        trigger.trigger_id,
                        trigger.workflow_id,
                        int(trigger.enabled),
                        trigger.created_at,
                        json.dumps(trigger.model_dump(mode="json")),
                    ),
                )
        return trigger

    def get_trigger(self, trigger_id: str) -> Optional[EmailTrigger]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT record_json FROM email_triggers WHERE trigger_id = ?", (trigger_id,)
            ).fetchone()
        return EmailTrigger(**json.loads(row["record_json"])) if row else None

    def list_triggers(self, enabled_only: bool = False) -> List[EmailTrigger]:
        sql = "SELECT record_json FROM email_triggers"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        with self._get_connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [EmailTrigger(**json.loads(r["record_json"])) for r in rows]

    def delete_trigger(self, trigger_id: str) -> bool:
        with self._get_connection() as conn:
            with conn:
                cur = conn.execute("DELETE FROM email_triggers WHERE trigger_id = ?", (trigger_id,))
        return cur.rowcount > 0

    # ---------------------------------------------------------------------- runs

    def insert_run_if_new(self, run: WorkflowRun) -> bool:
        """Insert a run unless this trigger already recorded the same message. Returns True if inserted."""
        with self._get_connection() as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO workflow_runs
                        (run_id, trigger_id, workflow_id, message_id, status, created_at, record_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.trigger_id,
                        run.workflow_id,
                        run.source_email.message_id,
                        run.status.value,
                        run.created_at,
                        json.dumps(run.model_dump(mode="json")),
                    ),
                )
        return cur.rowcount > 0

    def has_message(self, trigger_id: str, message_id: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM workflow_runs WHERE trigger_id = ? AND message_id = ?",
                (trigger_id, message_id),
            ).fetchone()
        return row is not None

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        run.updated_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    "UPDATE workflow_runs SET status = ?, record_json = ? WHERE run_id = ?",
                    (run.status.value, json.dumps(run.model_dump(mode="json")), run.run_id),
                )
        return run

    def transition_run(
        self,
        run_id: str,
        from_statuses: Iterable[RunStatus],
        to_status: RunStatus,
        decided_by: Optional[str] = None,
    ) -> Optional[WorkflowRun]:
        """Atomically move a run between states. Returns None if it was not in one of `from_statuses`.

        This is what stops a double-click (or two operators) from executing the same run twice.
        """
        allowed = [s.value for s in from_statuses]
        placeholders = ",".join("?" for _ in allowed)
        with self._get_connection() as conn:
            with conn:
                cur = conn.execute(
                    f"UPDATE workflow_runs SET status = ? WHERE run_id = ? AND status IN ({placeholders})",
                    (to_status.value, run_id, *allowed),
                )
                if cur.rowcount != 1:
                    return None
                row = conn.execute(
                    "SELECT record_json FROM workflow_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                run = WorkflowRun(**json.loads(row["record_json"]))
                run.status = to_status
                run.updated_at = datetime.now(timezone.utc).isoformat()
                if decided_by:
                    run.decided_by = decided_by
                conn.execute(
                    "UPDATE workflow_runs SET record_json = ? WHERE run_id = ?",
                    (json.dumps(run.model_dump(mode="json")), run_id),
                )
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT record_json FROM workflow_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return WorkflowRun(**json.loads(row["record_json"])) if row else None

    def list_runs(
        self,
        statuses: Optional[Iterable[RunStatus]] = None,
        trigger_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkflowRun]:
        clauses: List[str] = []
        params: List[object] = []
        if statuses:
            vals = [s.value for s in statuses]
            clauses.append(f"status IN ({','.join('?' for _ in vals)})")
            params.extend(vals)
        if trigger_id:
            clauses.append("trigger_id = ?")
            params.append(trigger_id)
        sql = "SELECT record_json FROM workflow_runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [WorkflowRun(**json.loads(r["record_json"])) for r in rows]
