"""Execution Repository (Phase 8).

Provides SQLite persistence for ExecutionAuditRecord entities.
Guarantees that execution histories, step outcomes, and audit logs survive restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional

from app.models.execution import ExecutionAuditRecord, ExecutionOverallStatus


class ExecutionRepository:
    """Manages SQLite persistence for workflow execution audit records."""

    def __init__(self, db_path: str = "workflowos.db") -> None:
        self.db_path = db_path
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._memory_conn is not None:
            yield self._memory_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _init_db(self) -> None:
        """Create execution_records table if it does not exist."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_records (
                        execution_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        execution_plan_id TEXT NOT NULL,
                        idempotency_key TEXT,
                        status TEXT NOT NULL,
                        execution_mode TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        record_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_exec_workflow_id
                    ON execution_records(workflow_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_exec_plan_id
                    ON execution_records(execution_plan_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_exec_idempotency
                    ON execution_records(idempotency_key)
                    """
                )

    def save(self, record: ExecutionAuditRecord) -> ExecutionAuditRecord:
        """Insert or replace an ExecutionAuditRecord in SQLite."""
        record_dict = record.model_dump(mode="json")
        record_json = json.dumps(record_dict)

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO execution_records (
                        execution_id,
                        workflow_id,
                        execution_plan_id,
                        idempotency_key,
                        status,
                        execution_mode,
                        start_time,
                        end_time,
                        record_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(execution_id) DO UPDATE SET
                        status = excluded.status,
                        end_time = excluded.end_time,
                        record_json = excluded.record_json
                    """,
                    (
                        record.execution_id,
                        record.workflow_id,
                        record.execution_plan_id,
                        record.idempotency_key,
                        record.status.value,
                        record.execution_mode.value,
                        record.start_time,
                        record.end_time,
                        record_json,
                    ),
                )
        return record

    def get_by_id(self, execution_id: str) -> Optional[ExecutionAuditRecord]:
        """Fetch an execution record by its execution_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT record_json FROM execution_records WHERE execution_id = ?
                """,
                (execution_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        data = json.loads(row["record_json"])
        return ExecutionAuditRecord(**data)

    def get_by_idempotency_key(self, key: str) -> Optional[ExecutionAuditRecord]:
        """Find an existing execution by its idempotency key."""
        if not key or not key.strip():
            return None

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT record_json FROM execution_records
                WHERE idempotency_key = ?
                ORDER BY start_time DESC
                LIMIT 1
                """,
                (key,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        data = json.loads(row["record_json"])
        return ExecutionAuditRecord(**data)

    def list_all(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ExecutionAuditRecord]:
        """Fetch all execution records, optionally filtered by workflow_id."""
        with self._get_connection() as conn:
            if workflow_id:
                cursor = conn.execute(
                    """
                    SELECT record_json FROM execution_records
                    WHERE workflow_id = ?
                    ORDER BY start_time DESC
                    LIMIT ?
                    """,
                    (workflow_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT record_json FROM execution_records
                    ORDER BY start_time DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()

        records: List[ExecutionAuditRecord] = []
        for row in rows:
            data = json.loads(row["record_json"])
            records.append(ExecutionAuditRecord(**data))
        return records
