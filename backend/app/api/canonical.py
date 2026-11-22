"""Canonical Workflow Specification API endpoints.

Provides REST endpoints for:
1. Generating formal CanonicalWorkflowSpec from validated SemanticWorkflow
2. Listing and retrieving canonical workflow specifications
3. Human approval governance (Approve / Reject)
4. Parameter binding customization (editing semantic variable names)

STRICT ARCHITECTURAL GUARANTEE:
Approval changes workflow governance state only. No browser automation,
mouse/keyboard input, or API calls to external services are executed.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dna import _generate_dna_from_events
from app.api.events import get_event_service
from app.api.semantic import get_semantic_engine
from app.models.canonical import (
    ApprovalActionRequest,
    ApprovalState,
    CanonicalWorkflowSpec,
    ParameterUpdateRequest,
    SpecificationListResponse,
)
from app.models.dna import WorkflowDNA
from app.repositories.canonical_repository import CanonicalWorkflowRepository, WorkflowConflict
from app.security import current_actor
from app.services.canonical_factory import CanonicalWorkflowFactory
from app.services.event_service import EventService
from app.services.semantic_engine import SemanticUnderstandingEngine
from app.services import workflow_editor

router = APIRouter(prefix="/api/workflows", tags=["Canonical Workflow Specification"])

# Global repository and factory instances
_canonical_repository: Optional[CanonicalWorkflowRepository] = None
_canonical_factory: Optional[CanonicalWorkflowFactory] = None


def get_canonical_repository() -> CanonicalWorkflowRepository:
    global _canonical_repository
    if _canonical_repository is None:
        _canonical_repository = CanonicalWorkflowRepository()  # the configured database (DATABASE_URL or file)
    return _canonical_repository


def get_canonical_factory() -> CanonicalWorkflowFactory:
    global _canonical_factory
    if _canonical_factory is None:
        _canonical_factory = CanonicalWorkflowFactory()
    return _canonical_factory


@router.post("/{semantic_workflow_id}/specification", response_model=CanonicalWorkflowSpec, status_code=status.HTTP_201_CREATED)
def create_canonical_specification_endpoint(
    semantic_workflow_id: str,
    event_service: EventService = Depends(get_event_service),
    engine: SemanticUnderstandingEngine = Depends(get_semantic_engine),
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
    factory: CanonicalWorkflowFactory = Depends(get_canonical_factory),
) -> CanonicalWorkflowSpec:
    """Generate and persist a CanonicalWorkflowSpec from a validated SemanticWorkflow."""
    # 1. Retrieve the validated semantic workflow
    semantic_wf = engine.get_interpretation_by_id(semantic_workflow_id)
    if not semantic_wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validated Semantic Workflow '{semantic_workflow_id}' not found. Please interpret WorkflowDNA first.",
        )

    # The same observed routine always yields the same DNA id; reuse its workflow instead of
    # piling up duplicates every time someone clicks "create" again. Rejected ones can be redone.
    existing = repository.get_by_dna_id(semantic_wf.source_dna_id)
    if existing and existing.approval_state.state != ApprovalState.REJECTED:
        return existing

    # 2. Find the corresponding source WorkflowDNA
    dna_items = _generate_dna_from_events(
        service=event_service,
        limit=500,
        inactivity_timeout=120.0,
        min_occurrences=2,
        similarity_threshold=0.65,
    )
    matching_dna = next((d for d in dna_items if d.dna_id == semantic_wf.source_dna_id), None)
    if not matching_dna:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source WorkflowDNA '{semantic_wf.source_dna_id}' could not be located in event history.",
        )

    # 3. Create canonical specification combining DNA + Semantic + Risk + Parameter Binding
    try:
        spec = factory.create_specification(dna=matching_dna, semantic_wf=semantic_wf)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate canonical specification: {val_err}",
        )

    # 4. Persist to SQLite
    saved_spec = repository.save(spec)
    return saved_spec


@router.get("/specifications", response_model=SpecificationListResponse)
def list_canonical_specifications_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
) -> SpecificationListResponse:
    """Fetch all stored canonical workflow specifications."""
    specs = repository.list_all(limit=limit)
    return SpecificationListResponse(
        total_count=len(specs),
        specifications=specs,
    )


@router.get("/specifications/{workflow_id}", response_model=CanonicalWorkflowSpec)
def get_canonical_specification_endpoint(
    workflow_id: str,
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
) -> CanonicalWorkflowSpec:
    """Fetch a single canonical workflow specification by its workflow_id."""
    spec = repository.get_by_id(workflow_id)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical Workflow Specification '{workflow_id}' not found.",
        )
    return spec


@router.post("/specifications/{workflow_id}/approve", response_model=CanonicalWorkflowSpec)
def approve_canonical_specification_endpoint(
    workflow_id: str,
    payload: ApprovalActionRequest = ApprovalActionRequest(),
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
    actor: str = Depends(current_actor),
) -> CanonicalWorkflowSpec:
    """Approve a canonical workflow specification.

    IMPORTANT SAFETY GUARANTEE:
    Approval confirms human acceptance of the workflow contract.
    It does NOT execute any automated tasks, browser actions, or external mutations.
    """
    try:
        updated = repository.update_approval_state(
            workflow_id=workflow_id,
            new_state=ApprovalState.APPROVED,
            reviewer=actor,
            comments=payload.comments,
            expected_version=payload.version,
        )
    except WorkflowConflict as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical Workflow Specification '{workflow_id}' not found.",
        )
    return updated


@router.post("/specifications/{workflow_id}/reject", response_model=CanonicalWorkflowSpec)
def reject_canonical_specification_endpoint(
    workflow_id: str,
    payload: ApprovalActionRequest,
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
    actor: str = Depends(current_actor),
) -> CanonicalWorkflowSpec:
    """Reject a canonical workflow specification with an optional explanation."""
    try:
        updated = repository.update_approval_state(
            workflow_id=workflow_id,
            new_state=ApprovalState.REJECTED,
            reviewer=actor,
            comments=payload.comments,
            rejection_reason=payload.reason,
            expected_version=payload.version,
        )
    except WorkflowConflict as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical Workflow Specification '{workflow_id}' not found.",
        )
    return updated


@router.patch("/specifications/{workflow_id}/parameters", response_model=CanonicalWorkflowSpec)
def update_specification_parameters_endpoint(
    workflow_id: str,
    payload: ParameterUpdateRequest,
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
) -> CanonicalWorkflowSpec:
    """Update human-assigned semantic names for bound workflow parameters.

    The underlying DNA source parameter names remain immutable.
    """
    try:
        updated = repository.update_parameters(
            workflow_id=workflow_id,
            updates=payload.updates,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canonical Workflow Specification '{workflow_id}' not found.",
        )
    return updated


# ------------------------------------------------------------------- workflow editor


def _spec_or_404(repository: CanonicalWorkflowRepository, workflow_id: str) -> CanonicalWorkflowSpec:
    spec = repository.get_by_id(workflow_id)
    if not spec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    return spec


@router.get("/specifications/{workflow_id}/definition")
def get_workflow_definition(
    workflow_id: str, repository: CanonicalWorkflowRepository = Depends(get_canonical_repository)
) -> Dict[str, Any]:
    """The workflow as the editor shows it: runnable steps and where each input comes from."""
    return workflow_editor.current_definition(_spec_or_404(repository, workflow_id))


@router.post("/specifications/{workflow_id}/definition/validate")
def validate_workflow_definition(
    workflow_id: str,
    definition: workflow_editor.WorkflowDefinition,
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
) -> Dict[str, Any]:
    """Check an edit without saving it (errors block saving; warnings are shown)."""
    spec = _spec_or_404(repository, workflow_id)
    issues = workflow_editor.validate(spec, definition)
    return {"valid": not any(i.level == "error" for i in issues), "issues": [i.model_dump() for i in issues]}


@router.put("/specifications/{workflow_id}/definition", response_model=CanonicalWorkflowSpec)
def save_workflow_definition(
    workflow_id: str,
    definition: workflow_editor.WorkflowDefinition,
    repository: CanonicalWorkflowRepository = Depends(get_canonical_repository),
    actor: str = Depends(current_actor),
) -> CanonicalWorkflowSpec:
    """Save an edit as the next version. The workflow goes back to 'requires review': nothing runs
    (manually or from a trigger) until someone approves the new version."""
    spec = _spec_or_404(repository, workflow_id)
    if spec.version != definition.base_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This workflow is now version {spec.version}; your changes start from {definition.base_version}. Reload it.",
        )
    issues = workflow_editor.validate(spec, definition)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "The workflow has problems to fix first.", "issues": [i.model_dump() for i in issues]},
        )
    edited = workflow_editor.apply(spec, definition, actor)
    changes = workflow_editor.changes_between(spec, edited)
    if all(c["kind"] == "context" for c in changes):  # dropping recorded context alone is not an edit
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing changed.")
    try:
        return repository.save_edit(spec, edited, actor, definition.note, changes)
    except WorkflowConflict as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/specifications/{workflow_id}/versions")
def list_workflow_versions(
    workflow_id: str, repository: CanonicalWorkflowRepository = Depends(get_canonical_repository)
) -> Dict[str, Any]:
    spec = _spec_or_404(repository, workflow_id)
    versions = repository.list_versions(workflow_id)
    if not versions:  # never edited: the recorded version is the only one
        versions = [{"version": spec.version, "created_at": spec.created_at, "created_by": None,
                     "note": "As discovered from recorded activity", "changes": []}]
    return {"current_version": spec.version, "versions": versions}


@router.get("/specifications/{workflow_id}/versions/{version}", response_model=CanonicalWorkflowSpec)
def get_workflow_version(
    workflow_id: str, version: str, repository: CanonicalWorkflowRepository = Depends(get_canonical_repository)
) -> CanonicalWorkflowSpec:
    spec = _spec_or_404(repository, workflow_id)
    if version == spec.version:
        return spec
    old = repository.get_version(workflow_id, version)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found.")
    return old
