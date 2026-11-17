"""Canonical Workflow Specification Repository.

Persistence for CanonicalWorkflowSpec entities: specifications, parameter bindings and human
approval states.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select

from app.db import Repository, canonical_workflows, upsert
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    ParameterUpdateItem,
)
from app.services.parameter_binder import ParameterBinder


class CanonicalWorkflowRepository(Repository):
    """Manages persistence for CanonicalWorkflowSpec entities."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        super().__init__(db_path)
        self.parameter_binder = ParameterBinder()

    def save(self, spec: CanonicalWorkflowSpec) -> CanonicalWorkflowSpec:
        """Insert or replace a CanonicalWorkflowSpec."""
        with self.begin() as conn:
            upsert(
                conn,
                canonical_workflows,
                {
                    "workflow_id": spec.workflow_id,
                    "source_dna_id": spec.source_dna_id,
                    "source_semantic_workflow_id": spec.source_semantic_workflow_id,
                    "title": spec.title,
                    "approval_state": spec.approval_state.state.value,
                    "overall_risk_level": spec.risk_assessment.overall_risk_level.value,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                    "spec_json": spec.model_dump(mode="json"),
                },
                key=["workflow_id"],
                update=[
                    "source_dna_id",
                    "source_semantic_workflow_id",
                    "title",
                    "approval_state",
                    "overall_risk_level",
                    "updated_at",
                    "spec_json",
                ],
            )
        return spec

    def _one(self, stmt) -> Optional[CanonicalWorkflowSpec]:
        with self.connect() as conn:
            data = conn.execute(stmt).scalar()
        return CanonicalWorkflowSpec(**data) if data else None

    def get_by_id(self, workflow_id: str) -> Optional[CanonicalWorkflowSpec]:
        return self._one(select(canonical_workflows.c.spec_json).where(canonical_workflows.c.workflow_id == workflow_id))

    def _latest_where(self, condition) -> Optional[CanonicalWorkflowSpec]:
        return self._one(
            select(canonical_workflows.c.spec_json)
            .where(condition)
            .order_by(canonical_workflows.c.updated_at.desc())
            .limit(1)
        )

    def get_by_semantic_id(self, semantic_id: str) -> Optional[CanonicalWorkflowSpec]:
        return self._latest_where(canonical_workflows.c.source_semantic_workflow_id == semantic_id)

    def get_by_dna_id(self, dna_id: str) -> Optional[CanonicalWorkflowSpec]:
        return self._latest_where(canonical_workflows.c.source_dna_id == dna_id)

    def list_all(self, limit: int = 50) -> List[CanonicalWorkflowSpec]:
        stmt = select(canonical_workflows.c.spec_json).order_by(canonical_workflows.c.updated_at.desc()).limit(limit)
        with self.connect() as conn:
            return [CanonicalWorkflowSpec(**data) for data in conn.execute(stmt).scalars()]

    def delete_all(self) -> int:
        with self.begin() as conn:
            return conn.execute(delete(canonical_workflows)).rowcount

    def update_approval_state(
        self,
        workflow_id: str,
        new_state: ApprovalState,
        reviewer: str = "user",
        comments: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> Optional[CanonicalWorkflowSpec]:
        """Transition the approval state of a workflow specification.

        STRICT PRINCIPLE:
        Approval modifies governance metadata only. It does NOT trigger
        any browser, API, desktop, or automated execution.
        """
        spec = self.get_by_id(workflow_id)
        if not spec:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        new_approval = ApprovalMetadata(
            state=new_state,
            reviewed_by=reviewer,
            reviewed_at=now_iso,
            rejection_reason=rejection_reason,
            comments=comments,
        )

        updated_spec = spec.model_copy(
            update={
                "approval_state": new_approval,
                "updated_at": now_iso,
            }
        )
        return self.save(updated_spec)

    def update_parameters(
        self,
        workflow_id: str,
        updates: List[ParameterUpdateItem],
    ) -> Optional[CanonicalWorkflowSpec]:
        """Update semantic names for bound parameters.

        Enforces:
        - DNA source_parameter remains completely unchanged.
        - Raises ValueError if source_parameter does not exist.
        """
        spec = self.get_by_id(workflow_id)
        if not spec:
            return None

        current_bindings = list(spec.variables)
        for item in updates:
            current_bindings = self.parameter_binder.update_binding_name(
                bindings=current_bindings,
                source_parameter=item.source_parameter,
                new_semantic_name=item.semantic_name,
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_spec = spec.model_copy(
            update={
                "variables": current_bindings,
                "parameter_bindings": current_bindings,
                "updated_at": now_iso,
            }
        )
        return self.save(updated_spec)
