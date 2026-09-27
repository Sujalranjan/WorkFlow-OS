"""Verification Repository (Phase 9).

SQLite persistence for VerificationResult and VerificationCheck entities.
Ensures post-execution verification audits, check details, and cryptographic integrity evidence
survive backend restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional

from app.config import DATABASE_PATH
from app.models.verification import VerificationCheck, VerificationResult, VerificationStatus


class VerificationRepository:
    """Manages SQLite persistence for post-execution verification runs."""

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
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
        """Create workflow_verifications and verification_checks tables."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_verifications (
                        verification_run_id TEXT PRIMARY KEY,
                        execution_id TEXT NOT NULL,
                        workflow_id TEXT NOT NULL,
                        execution_plan_id TEXT NOT NULL,
                        overall_status TEXT NOT NULL,
                        verified_count INTEGER NOT NULL,
                        failed_count INTEGER NOT NULL,
                        unknown_count INTEGER NOT NULL,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        result_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_verif_execution_id
                    ON workflow_verifications(execution_id)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS verification_checks (
                        verification_id TEXT PRIMARY KEY,
                        verification_run_id TEXT NOT NULL,
                        execution_id TEXT NOT NULL,
                        planned_step_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        check_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_vcheck_run_id
                    ON verification_checks(verification_run_id)
                    """
                )

    def save(self, result: VerificationResult) -> VerificationResult:
        """Insert or replace a VerificationResult and its individual checks."""
        result_dict = result.model_dump(mode="json")
        result_json = json.dumps(result_dict)

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_verifications (
                        verification_run_id,
                        execution_id,
                        workflow_id,
                        execution_plan_id,
                        overall_status,
                        verified_count,
                        failed_count,
                        unknown_count,
                        started_at,
                        completed_at,
                        result_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(verification_run_id) DO UPDATE SET
                        overall_status = excluded.overall_status,
                        verified_count = excluded.verified_count,
                        failed_count = excluded.failed_count,
                        unknown_count = excluded.unknown_count,
                        completed_at = excluded.completed_at,
                        result_json = excluded.result_json
                    """,
                    (
                        result.verification_run_id,
                        result.execution_id,
                        result.workflow_id,
                        result.execution_plan_id,
                        result.overall_status.value if isinstance(result.overall_status, VerificationStatus) else str(result.overall_status),
                        result.verified_count,
                        result.failed_count,
                        result.unknown_count,
                        result.started_at,
                        result.completed_at,
                        result_json,
                    ),
                )

                # Persist checks
                for check in result.checks:
                    chk_json = json.dumps(check.model_dump(mode="json"))
                    conn.execute(
                        """
                        INSERT INTO verification_checks (
                            verification_id,
                            verification_run_id,
                            execution_id,
                            planned_step_id,
                            status,
                            check_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(verification_id) DO UPDATE SET
                            status = excluded.status,
                            check_json = excluded.check_json
                        """,
                        (
                            check.verification_id,
                            result.verification_run_id,
                            result.execution_id,
                            check.planned_step_id,
                            check.status.value if isinstance(check.status, VerificationStatus) else str(check.status),
                            chk_json,
                        ),
                    )

        return result

    def get_by_id(self, verification_run_id: str) -> Optional[VerificationResult]:
        """Retrieves a specific verification run by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM workflow_verifications WHERE verification_run_id = ?",
                (verification_run_id,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["result_json"])
            return VerificationResult.model_validate(data)

    def get_latest_by_execution_id(self, execution_id: str) -> Optional[VerificationResult]:
        """Retrieves the latest verification run for an execution run."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT result_json FROM workflow_verifications
                WHERE execution_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (execution_id,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["result_json"])
            return VerificationResult.model_validate(data)

    def list_by_execution_id(self, execution_id: str, limit: int = 50) -> List[VerificationResult]:
        """Lists verification runs for a specific execution."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT result_json FROM workflow_verifications
                WHERE execution_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (execution_id, limit),
            ).fetchall()
            return [VerificationResult.model_validate(json.loads(r["result_json"])) for r in rows]

    def list_all(self, limit: int = 100) -> List[VerificationResult]:
        """Lists verification runs across all executions."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT result_json FROM workflow_verifications
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [VerificationResult.model_validate(json.loads(r["result_json"])) for r in rows]
