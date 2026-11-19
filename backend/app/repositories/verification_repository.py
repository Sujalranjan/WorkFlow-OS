"""Verification Repository: persistence for VerificationResult and VerificationCheck entities."""

from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, upsert, verification_checks, workflow_verifications
from app.models.verification import VerificationResult, VerificationStatus


def _status(value) -> str:
    return value.value if isinstance(value, VerificationStatus) else str(value)


class VerificationRepository(Repository):
    """Manages persistence for post-execution verification runs."""

    def save(self, result: VerificationResult) -> VerificationResult:
        """Insert or update a VerificationResult and its individual checks."""
        with self.begin() as conn:
            upsert(
                conn,
                workflow_verifications,
                {
                    "verification_run_id": result.verification_run_id,
                    "execution_id": result.execution_id,
                    "workflow_id": result.workflow_id,
                    "execution_plan_id": result.execution_plan_id,
                    "overall_status": _status(result.overall_status),
                    "verified_count": result.verified_count,
                    "failed_count": result.failed_count,
                    "unknown_count": result.unknown_count,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "result_json": result.model_dump(mode="json"),
                },
                key=["verification_run_id"],
                update=["overall_status", "verified_count", "failed_count", "unknown_count", "completed_at", "result_json"],
            )
            for check in result.checks:
                upsert(
                    conn,
                    verification_checks,
                    {
                        "verification_id": check.verification_id,
                        "verification_run_id": result.verification_run_id,
                        "execution_id": result.execution_id,
                        "planned_step_id": check.planned_step_id,
                        "status": _status(check.status),
                        "check_json": check.model_dump(mode="json"),
                    },
                    key=["verification_id"],
                    update=["status", "check_json"],
                )
        return result

    def _many(self, stmt) -> List[VerificationResult]:
        with self.connect() as conn:
            return [VerificationResult.model_validate(data) for data in conn.execute(stmt).scalars()]

    def get_by_id(self, verification_run_id: str) -> Optional[VerificationResult]:
        found = self._many(
            select(workflow_verifications.c.result_json).where(
                workflow_verifications.c.verification_run_id == verification_run_id
            )
        )
        return found[0] if found else None

    def get_latest_by_execution_id(self, execution_id: str) -> Optional[VerificationResult]:
        found = self.list_by_execution_id(execution_id, limit=1)
        return found[0] if found else None

    def list_by_execution_id(self, execution_id: str, limit: int = 50) -> List[VerificationResult]:
        return self._many(
            select(workflow_verifications.c.result_json)
            .where(workflow_verifications.c.execution_id == execution_id)
            .order_by(workflow_verifications.c.started_at.desc())
            .limit(limit)
        )

    def list_all(self, limit: int = 100) -> List[VerificationResult]:
        return self._many(
            select(workflow_verifications.c.result_json).order_by(workflow_verifications.c.started_at.desc()).limit(limit)
        )

    def delete_all(self) -> int:
        """Delete all verification runs and checks; returns the number of runs removed."""
        with self.begin() as conn:
            conn.execute(delete(verification_checks))
            return conn.execute(delete(workflow_verifications)).rowcount
