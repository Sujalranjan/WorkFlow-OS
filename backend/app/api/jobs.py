"""Background jobs: status of queued work, and dismissing jobs that need attention."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.jobs import Job, JobStatus
from app.security import current_actor
from app.services.jobs import get_queue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=List[Job])
def list_jobs(
    status_filter: Optional[List[JobStatus]] = Query(default=None, alias="status"),
    kind: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> List[Job]:
    return get_queue().list(statuses=status_filter, kind=kind, limit=limit)


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = get_queue().get(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job '{job_id}' not found.")
    return job


@router.post("/{job_id}/dismiss", response_model=Job)
def dismiss_job(job_id: str, actor: str = Depends(current_actor)) -> Job:
    """Close a job that failed or needs attention, after checking the systems it may have changed."""
    job = get_queue().dismiss(job_id, actor)
    if not job:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed jobs or jobs needing attention can be dismissed.")
    return job
