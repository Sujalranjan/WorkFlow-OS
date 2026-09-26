"""Workflow Learning & Reliability Intelligence API Router (Phase 11).

Provides endpoints to:
- Retrieve workflow reliability profile & step metrics: GET /api/workflows/{workflow_id}/learning
- Inspect historical learning audit events: GET /api/workflows/{workflow_id}/learning/events
- Refresh learning intelligence from execution & verification history: POST /api/workflows/{workflow_id}/learning/refresh
"""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, status

from app.models.learning import (
    WorkflowLearningEvent,
    WorkflowReliabilityProfile,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.learning_engine import LearningEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflow-learning"])

# Shared repositories and learning engine instance
execution_repo = ExecutionRepository()
verification_repo = VerificationRepository()
learning_repo = LearningRepository()
spec_repo = CanonicalWorkflowRepository()
learning_engine = LearningEngine(
    execution_repo=execution_repo,
    verification_repo=verification_repo,
    learning_repo=learning_repo,
    canonical_repo=spec_repo,
)


@router.get(
    "/{workflow_id}/learning",
    response_model=WorkflowReliabilityProfile,
    summary="Get workflow reliability profile and learning intelligence",
)
def get_workflow_learning_profile(workflow_id: str) -> WorkflowReliabilityProfile:
    """Returns the latest persisted reliability profile for the workflow.

    If no profile has been computed yet, computes and returns one based on existing execution history.
    """
    profile = learning_repo.get_profile(workflow_id)
    if profile:
        return profile

    # Otherwise compute fresh profile from history
    return learning_engine.analyze_workflow(workflow_id, persist=True)


@router.get(
    "/{workflow_id}/learning/events",
    response_model=List[WorkflowLearningEvent],
    summary="Get learning audit events for a workflow",
)
def get_workflow_learning_events(
    workflow_id: str,
    limit: int = 100,
) -> List[WorkflowLearningEvent]:
    """Returns the chronological audit trail of learning observations for the workflow."""
    return learning_repo.list_events(workflow_id, limit=limit)


@router.post(
    "/{workflow_id}/learning/refresh",
    response_model=WorkflowReliabilityProfile,
    summary="Deterministically recompute and persist workflow reliability intelligence",
)
def refresh_workflow_learning(workflow_id: str) -> WorkflowReliabilityProfile:
    """Aggregates all execution records and verification results to refresh reliability intelligence.

    Idempotent and deterministic: same history produces the exact same profile.
    """
    return learning_engine.analyze_workflow(workflow_id, persist=True)
