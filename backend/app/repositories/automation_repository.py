"""Persistence for email triggers and workflow runs.

The workflow_runs table doubles as the processed-email ledger: UNIQUE(trigger_id, message_id)
guarantees one run per message per trigger, across restarts and concurrent polls.
"""

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import delete, select, update

from app.db import Repository, email_triggers, insert_ignore, upsert, workflow_runs
from app.models.automation import EmailTrigger, RunStatus, WorkflowRun


class AutomationRepository(Repository):
    """Manages persistence for EmailTrigger and WorkflowRun records."""

    # ------------------------------------------------------------------ triggers

    def save_trigger(self, trigger: EmailTrigger) -> EmailTrigger:
        with self.begin() as conn:
            upsert(
                conn,
                email_triggers,
                {
                    "trigger_id": trigger.trigger_id,
                    "workflow_id": trigger.workflow_id,
                    "enabled": trigger.enabled,
                    "created_at": trigger.created_at,
                    "record_json": trigger.model_dump(mode="json"),
                },
                key=["trigger_id"],
            )
        return trigger

    def get_trigger(self, trigger_id: str) -> Optional[EmailTrigger]:
        with self.connect() as conn:
            data = conn.execute(
                select(email_triggers.c.record_json).where(email_triggers.c.trigger_id == trigger_id)
            ).scalar()
        return EmailTrigger(**data) if data else None

    def list_triggers(self, enabled_only: bool = False) -> List[EmailTrigger]:
        stmt = select(email_triggers.c.record_json)
        if enabled_only:
            stmt = stmt.where(email_triggers.c.enabled.is_(True))
        stmt = stmt.order_by(email_triggers.c.created_at.desc())
        with self.connect() as conn:
            return [EmailTrigger(**data) for data in conn.execute(stmt).scalars()]

    def delete_trigger(self, trigger_id: str) -> bool:
        with self.begin() as conn:
            return conn.execute(delete(email_triggers).where(email_triggers.c.trigger_id == trigger_id)).rowcount > 0

    # ---------------------------------------------------------------------- runs

    def insert_run_if_new(self, run: WorkflowRun) -> bool:
        """Insert a run unless this trigger already recorded the same message. Returns True if inserted."""
        with self.begin() as conn:
            return insert_ignore(
                conn,
                workflow_runs,
                {
                    "run_id": run.run_id,
                    "trigger_id": run.trigger_id,
                    "workflow_id": run.workflow_id,
                    "message_id": run.source_email.message_id,
                    "status": run.status.value,
                    "created_at": run.created_at,
                    "record_json": run.model_dump(mode="json"),
                },
            )

    def has_message(self, trigger_id: str, message_id: str) -> bool:
        stmt = select(workflow_runs.c.run_id).where(
            workflow_runs.c.trigger_id == trigger_id, workflow_runs.c.message_id == message_id
        )
        with self.connect() as conn:
            return conn.execute(stmt).first() is not None

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        run.updated_at = datetime.now(timezone.utc).isoformat()
        with self.begin() as conn:
            conn.execute(
                update(workflow_runs)
                .where(workflow_runs.c.run_id == run.run_id)
                .values(status=run.status.value, record_json=run.model_dump(mode="json"))
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
        with self.begin() as conn:
            moved = conn.execute(
                update(workflow_runs)
                .where(workflow_runs.c.run_id == run_id, workflow_runs.c.status.in_(allowed))
                .values(status=to_status.value)
            )
            if moved.rowcount != 1:
                return None
            data = conn.execute(select(workflow_runs.c.record_json).where(workflow_runs.c.run_id == run_id)).scalar()
            run = WorkflowRun(**data)
            run.status = to_status
            run.updated_at = datetime.now(timezone.utc).isoformat()
            if decided_by:
                run.decided_by = decided_by
            conn.execute(
                update(workflow_runs).where(workflow_runs.c.run_id == run_id).values(record_json=run.model_dump(mode="json"))
            )
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        with self.connect() as conn:
            data = conn.execute(select(workflow_runs.c.record_json).where(workflow_runs.c.run_id == run_id)).scalar()
        return WorkflowRun(**data) if data else None

    def list_runs(
        self,
        statuses: Optional[Iterable[RunStatus]] = None,
        trigger_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkflowRun]:
        stmt = select(workflow_runs.c.record_json)
        if statuses:
            stmt = stmt.where(workflow_runs.c.status.in_([s.value for s in statuses]))
        if trigger_id:
            stmt = stmt.where(workflow_runs.c.trigger_id == trigger_id)
        stmt = stmt.order_by(workflow_runs.c.created_at.desc()).limit(limit)
        with self.connect() as conn:
            return [WorkflowRun(**data) for data in conn.execute(stmt).scalars()]
