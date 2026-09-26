"""Execution Plan Repository (Phase 7).

Provides SQLite persistence for ExecutionPlan and DryRunResult entities.
Guarantees that generated plans and simulation results survive backend restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional

from app.models.execution_plan import DryRunResult, ExecutionPlan


class ExecutionPlanRepository:
    """Manages SQLite persistence for ExecutionPlan entities."""

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
        """Create execution_plans table if it does not exist."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_plans (
                        plan_id TEXT PRIMARY KEY,
                        source_workflow_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        dry_run_status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        plan_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_plan_workflow_id
                    ON execution_plans(source_workflow_id)
                    """
                )

    def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Insert or replace an ExecutionPlan in SQLite."""
        plan_dict = plan.model_dump(mode="json")
        plan_json = json.dumps(plan_dict)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO execution_plans (
                        plan_id,
                        source_workflow_id,
                        status,
                        dry_run_status,
                        created_at,
                        updated_at,
                        plan_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(plan_id) DO UPDATE SET
                        source_workflow_id = excluded.source_workflow_id,
                        status = excluded.status,
                        dry_run_status = excluded.dry_run_status,
                        updated_at = excluded.updated_at,
                        plan_json = excluded.plan_json
                    """,
                    (
                        plan.execution_plan_id,
                        plan.source_workflow_id,
                        plan.source_approval_state,
                        plan.dry_run_status,
                        plan.created_at,
                        now_iso,
                        plan_json,
                    ),
                )
        return plan

    def get_by_id(self, plan_id: str) -> Optional[ExecutionPlan]:
        """Fetch an execution plan by its plan_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT plan_json FROM execution_plans WHERE plan_id = ?
                """,
                (plan_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        data = json.loads(row["plan_json"])
        return ExecutionPlan(**data)

    def get_by_workflow_id(self, workflow_id: str) -> Optional[ExecutionPlan]:
        """Fetch latest execution plan for a source workflow specification."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT plan_json FROM execution_plans
                WHERE source_workflow_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workflow_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        data = json.loads(row["plan_json"])
        return ExecutionPlan(**data)

    def list_all(self, limit: int = 50) -> List[ExecutionPlan]:
        """Fetch all stored execution plans."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT plan_json FROM execution_plans
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        plans: List[ExecutionPlan] = []
        for row in rows:
            data = json.loads(row["plan_json"])
            plans.append(ExecutionPlan(**data))
        return plans

    def update_dry_run_result(
        self,
        plan_id: str,
        dry_run_result: DryRunResult,
    ) -> Optional[ExecutionPlan]:
        """Attach dry run simulation results to the execution plan and persist."""
        plan = self.get_by_id(plan_id)
        if not plan:
            return None

        updated_plan = plan.model_copy(
            update={
                "dry_run_status": dry_run_result.overall_simulation_status.lower(),
                "dry_run_result": dry_run_result,
            }
        )
        return self.save(updated_plan)
