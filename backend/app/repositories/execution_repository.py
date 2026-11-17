"""Execution Repository: persistence for ExecutionAuditRecord entities (execution history and audit logs)."""

from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, execution_records, upsert
from app.models.execution import ExecutionAuditRecord


class ExecutionRepository(Repository):
    """Manages persistence for workflow execution audit records."""

    def save(self, record: ExecutionAuditRecord) -> ExecutionAuditRecord:
        """Insert or update an ExecutionAuditRecord."""
        with self.begin() as conn:
            upsert(
                conn,
                execution_records,
                {
                    "execution_id": record.execution_id,
                    "workflow_id": record.workflow_id,
                    "execution_plan_id": record.execution_plan_id,
                    "idempotency_key": record.idempotency_key,
                    "status": record.status.value,
                    "execution_mode": record.execution_mode.value,
                    "start_time": record.start_time,
                    "end_time": record.end_time,
                    "record_json": record.model_dump(mode="json"),
                },
                key=["execution_id"],
                update=["status", "end_time", "idempotency_key", "record_json"],
            )
        return record

    def _one(self, stmt) -> Optional[ExecutionAuditRecord]:
        with self.connect() as conn:
            data = conn.execute(stmt).scalar()
        return ExecutionAuditRecord(**data) if data else None

    def get_by_id(self, execution_id: str) -> Optional[ExecutionAuditRecord]:
        return self._one(select(execution_records.c.record_json).where(execution_records.c.execution_id == execution_id))

    def get_by_idempotency_key(self, key: str) -> Optional[ExecutionAuditRecord]:
        """Find an existing execution by its idempotency key."""
        if not key or not key.strip():
            return None
        return self._one(
            select(execution_records.c.record_json)
            .where(execution_records.c.idempotency_key == key)
            .order_by(execution_records.c.start_time.desc())
            .limit(1)
        )

    def list_all(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[ExecutionAuditRecord]:
        """All execution records, newest first, optionally for one workflow."""
        stmt = select(execution_records.c.record_json)
        if workflow_id:
            stmt = stmt.where(execution_records.c.workflow_id == workflow_id)
        stmt = stmt.order_by(execution_records.c.start_time.desc()).limit(limit)
        with self.connect() as conn:
            return [ExecutionAuditRecord(**data) for data in conn.execute(stmt).scalars()]

    def delete_all(self) -> int:
        with self.begin() as conn:
            return conn.execute(delete(execution_records)).rowcount
