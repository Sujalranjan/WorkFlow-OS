"""Automation API: email triggers and the approval / intervention inbox for their runs.

    POST   /api/automation/triggers                  create a trigger for an approved workflow
    GET    /api/automation/triggers                  list triggers
    PATCH  /api/automation/triggers/{id}             enable/disable, change query or interval
    DELETE /api/automation/triggers/{id}             delete (existing runs are kept)
    POST   /api/automation/triggers/{id}/poll        check Gmail now
    GET    /api/automation/runs?status=...           list runs (inbox = PENDING_APPROVAL,NEEDS_INPUT)
    GET    /api/automation/runs/{id}                 run detail
    POST   /api/automation/runs/{id}/approve         approve and execute this run
    POST   /api/automation/runs/{id}/resume          supply missing input and continue
    POST   /api/automation/runs/{id}/reject          discard the run
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.automation import (
    CreateTriggerRequest,
    EmailTrigger,
    PollResult,
    ResumeRunRequest,
    RunStatus,
    UpdateTriggerRequest,
    WorkflowRun,
)
from app.security import current_actor
from app.services.trigger_service import TriggerError, TriggerService

router = APIRouter(prefix="/api/automation", tags=["automation"])

_service: Optional[TriggerService] = None


def get_trigger_service() -> TriggerService:
    global _service
    if _service is None:
        _service = TriggerService()
    return _service


def _call(fn, *args):
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TriggerError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/triggers", response_model=EmailTrigger, status_code=status.HTTP_201_CREATED)
def create_trigger(req: CreateTriggerRequest) -> EmailTrigger:
    try:
        return get_trigger_service().create_trigger(req)
    except TriggerError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/triggers", response_model=List[EmailTrigger])
def list_triggers() -> List[EmailTrigger]:
    return get_trigger_service().repo.list_triggers()


@router.patch("/triggers/{trigger_id}", response_model=EmailTrigger)
def update_trigger(trigger_id: str, req: UpdateTriggerRequest) -> EmailTrigger:
    return _call(get_trigger_service().update_trigger, trigger_id, req)


@router.delete("/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trigger(trigger_id: str) -> None:
    if not get_trigger_service().repo.delete_trigger(trigger_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trigger '{trigger_id}' not found.")


@router.post("/triggers/{trigger_id}/poll", response_model=PollResult)
def poll_trigger(trigger_id: str) -> PollResult:
    return _call(get_trigger_service().poll, trigger_id)


@router.get("/runs", response_model=List[WorkflowRun])
def list_runs(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Comma-separated RunStatus values"),
    trigger_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> List[WorkflowRun]:
    statuses = None
    if status_filter:
        try:
            statuses = [RunStatus(s.strip().upper()) for s in status_filter.split(",") if s.strip()]
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return get_trigger_service().repo.list_runs(statuses=statuses, trigger_id=trigger_id, limit=limit)


@router.get("/runs/{run_id}", response_model=WorkflowRun)
def get_run(run_id: str) -> WorkflowRun:
    run = get_trigger_service().repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found.")
    return run


@router.post("/runs/{run_id}/approve", response_model=WorkflowRun)
def approve_run(run_id: str, actor: str = Depends(current_actor)) -> WorkflowRun:
    return _call(get_trigger_service().approve_run, run_id, actor)


@router.post("/runs/{run_id}/resume", response_model=WorkflowRun)
def resume_run(run_id: str, req: ResumeRunRequest, actor: str = Depends(current_actor)) -> WorkflowRun:
    return _call(get_trigger_service().resume_run, run_id, req.inputs, actor)


@router.post("/runs/{run_id}/reject", response_model=WorkflowRun)
def reject_run(run_id: str, actor: str = Depends(current_actor)) -> WorkflowRun:
    return _call(get_trigger_service().reject_run, run_id, actor)
