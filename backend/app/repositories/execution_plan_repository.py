"""Execution Plan Repository: persistence for ExecutionPlan and DryRunResult entities."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, execution_plans, upsert
from app.models.execution_plan import DryRunResult, ExecutionPlan


class ExecutionPlanRepository(Repository):
    """Manages persistence for ExecutionPlan entities."""

    def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Insert or replace an ExecutionPlan."""
        with self.begin() as conn:
            upsert(
                conn,
                execution_plans,
                {
                    "plan_id": plan.execution_plan_id,
                    "source_workflow_id": plan.source_workflow_id,
                    "status": plan.source_approval_state,
                    "dry_run_status": plan.dry_run_status,
                    "created_at": plan.created_at,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "plan_json": plan.model_dump(mode="json"),
                },
                key=["plan_id"],
                update=["source_workflow_id", "status", "dry_run_status", "updated_at", "plan_json"],
            )
        return plan

    def _one(self, stmt) -> Optional[ExecutionPlan]:
        with self.connect() as conn:
            data = conn.execute(stmt).scalar()
        return ExecutionPlan(**data) if data else None

    def get_by_id(self, plan_id: str) -> Optional[ExecutionPlan]:
        return self._one(select(execution_plans.c.plan_json).where(execution_plans.c.plan_id == plan_id))

    def get_by_workflow_id(self, workflow_id: str) -> Optional[ExecutionPlan]:
        """Latest execution plan for a workflow specification."""
        return self._one(
            select(execution_plans.c.plan_json)
            .where(execution_plans.c.source_workflow_id == workflow_id)
            .order_by(execution_plans.c.updated_at.desc())
            .limit(1)
        )

    def list_all(self, limit: int = 50) -> List[ExecutionPlan]:
        stmt = select(execution_plans.c.plan_json).order_by(execution_plans.c.updated_at.desc()).limit(limit)
        with self.connect() as conn:
            return [ExecutionPlan(**data) for data in conn.execute(stmt).scalars()]

    def update_dry_run_result(self, plan_id: str, dry_run_result: DryRunResult) -> Optional[ExecutionPlan]:
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

    def delete_all(self) -> int:
        with self.begin() as conn:
            return conn.execute(delete(execution_plans)).rowcount
