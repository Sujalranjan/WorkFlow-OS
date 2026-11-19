"""What each kind of background job does, and how the API submits jobs.

Kinds:
    execute_plan       run an approved execution plan (LIVE or DRY_RUN)
    verify_execution   independently verify an execution (read-only)
    execute_run        plan + execute + verify + learn for an approved email-triggered run
    resume_run         continue a run that paused for input
    poll_triggers      check Gmail for every due email trigger (scheduled by the worker)

A handler calls `ctx.side_effects()` right before anything that may change the outside world.
After that point the job is never retried: if it fails or the worker dies, it needs attention.
"""

from dataclasses import dataclass
import logging
from typing import Any, Callable, Dict, Optional

import httpx
from sqlalchemy.exc import OperationalError

from app import config
from app.models.jobs import Job
from app.services.job_queue import JobQueue

logger = logging.getLogger(__name__)

POLL_TRIGGERS = "poll_triggers"

# Errors worth retrying when they happen before any side effect.
TRANSIENT_ERRORS = (httpx.TransportError, OperationalError, ConnectionError, TimeoutError)


@dataclass
class JobContext:
    job: Job
    queue: JobQueue

    def side_effects(self) -> None:
        if not self.job.side_effects_started:
            self.queue.mark_side_effects(self.job.job_id)
            self.job.side_effects_started = True


Handler = Callable[[Dict[str, Any], JobContext], Optional[Dict[str, Any]]]


# ------------------------------------------------------------------ services
# Resolved lazily so tests can swap the module-level singletons the API uses.


def _execution_api():
    from app.api import execution

    return execution


def _trigger_service():
    from app.api.automation import get_trigger_service

    return get_trigger_service()


# ------------------------------------------------------------------ handlers


def execute_plan(payload: Dict[str, Any], ctx: JobContext) -> Dict[str, Any]:
    from app.models.execution import ExecutionMode

    mode = ExecutionMode(payload.get("execution_mode", ExecutionMode.LIVE.value))
    if mode == ExecutionMode.LIVE:
        ctx.side_effects()
    record = _execution_api().execution_engine.execute_plan(
        execution_plan_id=payload["execution_plan_id"],
        idempotency_key=payload.get("idempotency_key") or f"job:{ctx.job.job_id}:{ctx.job.attempts}",
        execution_mode=mode,
        custom_sandbox_dir=payload.get("sandbox_dir"),
        executed_by=payload.get("executed_by") or ctx.job.created_by or "worker",
    )
    return {"execution_id": record.execution_id, "status": record.status.value, "error_summary": record.error_summary}


def verify_execution(payload: Dict[str, Any], ctx: JobContext) -> Dict[str, Any]:
    result = _execution_api().verification_engine.verify_execution(
        execution_id=payload["execution_id"],
        force_recheck=payload.get("force_recheck", True),
        custom_expectations=payload.get("custom_expectations"),
    )
    return {
        "execution_id": result.execution_id,
        "verification_run_id": result.verification_run_id,
        "overall_status": result.overall_status.value,
    }


def execute_run(payload: Dict[str, Any], ctx: JobContext) -> Dict[str, Any]:
    run = _trigger_service().execute_claimed_run(payload["run_id"], payload["decided_by"], before_execute=ctx.side_effects)
    return {"run_id": run.run_id, "status": run.status.value, "execution_id": run.execution_id, "error": run.error}


def resume_run(payload: Dict[str, Any], ctx: JobContext) -> Dict[str, Any]:
    from app.services.trigger_service import TriggerError

    service = _trigger_service()
    try:
        run = service.continue_claimed_run(
            payload["run_id"], payload.get("inputs", {}), payload["decided_by"], before_execute=ctx.side_effects
        )
    except TriggerError as e:
        # The input was not accepted; nothing ran and the run waits for a corrected value.
        run = service.repo.get_run(payload["run_id"])
        return {"run_id": payload["run_id"], "status": run.status.value if run else None, "error": str(e)}
    return {"run_id": run.run_id, "status": run.status.value, "execution_id": run.execution_id, "error": run.error}


def poll_triggers(payload: Dict[str, Any], ctx: JobContext) -> Dict[str, Any]:
    results = _trigger_service().poll_due()
    return {
        "triggers_polled": len(results),
        "new_runs": sum(len(r.new_runs) for r in results),
        "errors": [r.error for r in results if r.error],
    }


HANDLERS: Dict[str, Handler] = {
    "execute_plan": execute_plan,
    "verify_execution": verify_execution,
    "execute_run": execute_run,
    "resume_run": resume_run,
    POLL_TRIGGERS: poll_triggers,
}


# ------------------------------------------------- after an interrupted job


def on_needs_attention(job: Job) -> None:
    """Make the interruption visible where people look (the run in the Inbox, the execution record)."""
    reason = job.last_error or "Interrupted while it may have changed external systems."
    try:
        if job.kind in ("execute_run", "resume_run"):
            _trigger_service().mark_interrupted(job.payload["run_id"], reason)
        elif job.kind == "execute_plan":
            from app.models.execution import ExecutionOverallStatus

            api = _execution_api()
            key = job.payload.get("idempotency_key") or f"job:{job.job_id}:{job.attempts}"
            record = api.exec_repo.get_by_idempotency_key(key)
            if record and record.status == ExecutionOverallStatus.RUNNING:
                record.status = ExecutionOverallStatus.FAILED
                record.error_summary = f"Interrupted: {reason}"
                api.exec_repo.save(record)
    except Exception:  # noqa: BLE001 - reporting must never break the worker
        logger.exception("Could not record the interruption of job %s", job.job_id)


# ------------------------------------------------------------------ submit


def get_queue() -> JobQueue:
    return JobQueue()


def submit(kind: str, payload: Dict[str, Any], created_by: Optional[str], max_attempts: Optional[int] = None) -> Job:
    """Queue a job for the worker. With JOBS_INLINE (tests), run it right away in this thread."""
    if kind not in HANDLERS:
        raise ValueError(f"Unknown job kind '{kind}'.")
    queue = get_queue()
    job = queue.enqueue(kind, payload, created_by=created_by, max_attempts=max_attempts or config.JOB_MAX_ATTEMPTS)
    if config.JOBS_INLINE:
        from app.worker import Worker

        Worker(queue=queue, worker_id="inline").process(job.job_id)
        job = queue.get(job.job_id)
    return job
