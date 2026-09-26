"""Canonical Workflow Specification Repository (Phase 6).

Provides SQLite persistence for CanonicalWorkflowSpec entities.
Guarantees that canonical specifications, parameter bindings, and human
approval states survive backend restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Generator, List, Optional

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    ParameterUpdateItem,
)
from app.services.parameter_binder import ParameterBinder


class CanonicalWorkflowRepository:
    """Manages SQLite persistence for CanonicalWorkflowSpec entities."""

    def __init__(self, db_path: str = "workflowos.db") -> None:
        self.db_path = db_path
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()
        self.parameter_binder = ParameterBinder()

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
        """Create canonical_workflows table if it does not exist."""
        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canonical_workflows (
                        workflow_id TEXT PRIMARY KEY,
                        source_dna_id TEXT NOT NULL,
                        source_semantic_workflow_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        approval_state TEXT NOT NULL,
                        overall_risk_level TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        spec_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_canonical_dna_id
                    ON canonical_workflows(source_dna_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_canonical_sem_id
                    ON canonical_workflows(source_semantic_workflow_id)
                    """
                )

    def save(self, spec: CanonicalWorkflowSpec) -> CanonicalWorkflowSpec:
        """Insert or replace a CanonicalWorkflowSpec in SQLite."""
        spec_dict = spec.model_dump(mode="json")
        spec_json = json.dumps(spec_dict)

        with self._get_connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO canonical_workflows (
                        workflow_id,
                        source_dna_id,
                        source_semantic_workflow_id,
                        title,
                        approval_state,
                        overall_risk_level,
                        created_at,
                        updated_at,
                        spec_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        source_dna_id = excluded.source_dna_id,
                        source_semantic_workflow_id = excluded.source_semantic_workflow_id,
                        title = excluded.title,
                        approval_state = excluded.approval_state,
                        overall_risk_level = excluded.overall_risk_level,
                        updated_at = excluded.updated_at,
                        spec_json = excluded.spec_json
                    """,
                    (
                        spec.workflow_id,
                        spec.source_dna_id,
                        spec.source_semantic_workflow_id,
                        spec.title,
                        spec.approval_state.state.value,
                        spec.risk_assessment.overall_risk_level.value,
                        spec.created_at,
                        spec.updated_at,
                        spec_json,
                    ),
                )
        return spec

    def get_by_id(self, workflow_id: str) -> Optional[CanonicalWorkflowSpec]:
        """Fetch a canonical workflow specification by its workflow_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT spec_json FROM canonical_workflows WHERE workflow_id = ?
                """,
                (workflow_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        spec_data = json.loads(row["spec_json"])
        return CanonicalWorkflowSpec(**spec_data)

    def get_by_semantic_id(self, semantic_id: str) -> Optional[CanonicalWorkflowSpec]:
        """Fetch a canonical workflow specification by source_semantic_workflow_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT spec_json FROM canonical_workflows
                WHERE source_semantic_workflow_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (semantic_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        spec_data = json.loads(row["spec_json"])
        return CanonicalWorkflowSpec(**spec_data)

    def get_by_dna_id(self, dna_id: str) -> Optional[CanonicalWorkflowSpec]:
        """Fetch a canonical workflow specification by source_dna_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT spec_json FROM canonical_workflows
                WHERE source_dna_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (dna_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        spec_data = json.loads(row["spec_json"])
        return CanonicalWorkflowSpec(**spec_data)

    def list_all(self, limit: int = 50) -> List[CanonicalWorkflowSpec]:
        """Fetch all stored canonical workflow specifications."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT spec_json FROM canonical_workflows
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        specs: List[CanonicalWorkflowSpec] = []
        for row in rows:
            spec_data = json.loads(row["spec_json"])
            specs.append(CanonicalWorkflowSpec(**spec_data))
        return specs

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
