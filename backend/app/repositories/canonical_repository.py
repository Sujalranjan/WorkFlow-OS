"""Canonical Workflow Specification Repository.

Persistence for CanonicalWorkflowSpec entities: specifications, parameter bindings and human
approval states.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.db import Repository, canonical_workflows, upsert, workflow_versions
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    ParameterUpdateItem,
)
from app.services.parameter_binder import ParameterBinder


class WorkflowConflict(Exception):
    """The workflow changed since the caller read it (another edit or decision came first)."""


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

    def _row(self, spec: CanonicalWorkflowSpec) -> Dict[str, Any]:
        return {
            "source_dna_id": spec.source_dna_id,
            "source_semantic_workflow_id": spec.source_semantic_workflow_id,
            "title": spec.title,
            "approval_state": spec.approval_state.state.value,
            "overall_risk_level": spec.risk_assessment.overall_risk_level.value,
            "updated_at": spec.updated_at,
            "spec_json": spec.model_dump(mode="json"),
        }

    def _replace_if_unchanged(self, conn, spec: CanonicalWorkflowSpec, read_updated_at: str) -> None:
        """Write `spec` only if the stored row still has the `updated_at` the caller read."""
        res = conn.execute(
            update(canonical_workflows)
            .where(canonical_workflows.c.workflow_id == spec.workflow_id)
            .where(canonical_workflows.c.updated_at == read_updated_at)
            .values(**self._row(spec))
        )
        if res.rowcount != 1:
            raise WorkflowConflict("The workflow changed while you were working on it. Reload it and try again.")

    # ------------------------------------------------------------------ versions

    def save_edit(
        self,
        base: CanonicalWorkflowSpec,
        edited: CanonicalWorkflowSpec,
        actor: str,
        note: Optional[str],
        changes: List[Dict[str, Any]],
    ) -> CanonicalWorkflowSpec:
        """Store an edited version atomically: keep the base version in the history (once), add the
        new one, and replace the current spec only if nobody changed it since `base` was read."""
        try:
            with self.begin() as conn:
                has_base = conn.execute(
                    select(workflow_versions.c.version)
                    .where(workflow_versions.c.workflow_id == base.workflow_id)
                    .where(workflow_versions.c.version == base.version)
                ).first()
                if not has_base:
                    conn.execute(
                        insert(workflow_versions).values(
                            workflow_id=base.workflow_id,
                            version=base.version,
                            created_at=base.created_at,
                            created_by=None,
                            note="As discovered from recorded activity" if base.version == "1.0.0" else None,
                            changes=[],
                            spec_json=base.model_dump(mode="json"),
                        )
                    )
                conn.execute(
                    insert(workflow_versions).values(
                        workflow_id=edited.workflow_id,
                        version=edited.version,
                        created_at=edited.updated_at,
                        created_by=actor,
                        note=note,
                        changes=changes,
                        spec_json=edited.model_dump(mode="json"),
                    )
                )
                self._replace_if_unchanged(conn, edited, base.updated_at)
        except IntegrityError:  # the same new version was saved by someone else first
            raise WorkflowConflict("Someone saved a new version of this workflow first. Reload it and try again.")
        return edited

    def list_versions(self, workflow_id: str) -> List[Dict[str, Any]]:
        stmt = (
            select(
                workflow_versions.c.version,
                workflow_versions.c.created_at,
                workflow_versions.c.created_by,
                workflow_versions.c.note,
                workflow_versions.c.changes,
            )
            .where(workflow_versions.c.workflow_id == workflow_id)
            .order_by(workflow_versions.c.created_at.desc())
        )
        with self.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt)]

    def get_version(self, workflow_id: str, version: str) -> Optional[CanonicalWorkflowSpec]:
        stmt = (
            select(workflow_versions.c.spec_json)
            .where(workflow_versions.c.workflow_id == workflow_id)
            .where(workflow_versions.c.version == version)
        )
        with self.connect() as conn:
            data = conn.execute(stmt).scalar()
        return CanonicalWorkflowSpec(**data) if data else None

    def update_approval_state(
        self,
        workflow_id: str,
        new_state: ApprovalState,
        reviewer: str = "user",
        comments: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        expected_version: Optional[str] = None,
    ) -> Optional[CanonicalWorkflowSpec]:
        """Transition the approval state of a workflow specification.

        STRICT PRINCIPLE:
        Approval modifies governance metadata only. It does NOT trigger
        any browser, API, desktop, or automated execution.

        With `expected_version`, the decision is refused (WorkflowConflict) if the workflow is now
        another version than the one the reviewer looked at. The write itself only succeeds if
        nothing changed since it was read, so a concurrent edit is never overwritten.
        """
        spec = self.get_by_id(workflow_id)
        if not spec:
            return None
        if expected_version is not None and expected_version != spec.version:
            raise WorkflowConflict(
                f"This workflow is now version {spec.version}; you reviewed version {expected_version}. "
                "Review the new version before deciding."
            )

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
        with self.begin() as conn:
            self._replace_if_unchanged(conn, updated_spec, spec.updated_at)
        return updated_spec

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
