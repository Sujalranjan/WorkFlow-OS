"""Durable job queue in the main database (no Redis).

Claiming: on Postgres the next due job is selected with `FOR UPDATE SKIP LOCKED`, so several
workers never pick the same job and never block each other. On SQLite (development) a conditional
UPDATE does the same with a single writer.

Leases: a running job is owned by one worker until `locked_until`. The worker renews the lease while
it works. If a worker dies, the lease expires and `recover_expired()` decides what happens:

- the job never reached a step that could change the outside world -> queued again (retry), or
  failed once it has used up its attempts;
- it may have changed something (`side_effects_started`) -> NEEDS_ATTENTION, never replayed, so a
  CRM update or Slack message cannot happen twice. A person checks and dismisses it.

Failures raised by a handler follow the same rule: transient errors before any side effect are
retried with exponential backoff; everything else fails (or needs attention).
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select, update

from app.db import Repository, insert_ignore, jobs
from app.models.jobs import ACTIVE_JOB_STATUSES, Job, JobStatus

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300


def ts(moment: Optional[datetime] = None) -> str:
    """Fixed-width UTC timestamp: compares correctly as text on every database."""
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _job(row) -> Job:
    return Job(**dict(row._mapping))


class JobQueue(Repository):
    # ---------------------------------------------------------------- enqueue

    def enqueue(
        self,
        kind: str,
        payload: Dict[str, Any],
        created_by: Optional[str] = None,
        max_attempts: int = 3,
        dedupe_key: Optional[str] = None,
        delay_seconds: float = 0,
    ) -> Job:
        """Add a job. With `dedupe_key`, an already queued/running job with that key is returned instead."""
        now = datetime.now(timezone.utc)
        values = {
            "job_id": f"job-{uuid.uuid4().hex[:16]}",
            "kind": kind,
            "status": JobStatus.QUEUED.value,
            "payload": payload,
            "result": None,
            "attempts": 0,
            "max_attempts": max(1, max_attempts),
            "run_after": ts(now + timedelta(seconds=delay_seconds)),
            "side_effects_started": False,
            "dedupe_key": dedupe_key,
            "created_by": created_by,
            "created_at": ts(now),
        }
        with self.begin() as conn:
            if insert_ignore(conn, jobs, values):
                return self._get(conn, values["job_id"])
            existing = conn.execute(select(jobs).where(jobs.c.dedupe_key == dedupe_key)).first()
        if existing is None:  # pragma: no cover - the key was freed between the two statements
            return self.enqueue(kind, payload, created_by, max_attempts, dedupe_key, delay_seconds)
        return _job(existing)

    # ------------------------------------------------------------------ claim

    def claim(self, worker_id: str, lease_seconds: float = 60, job_id: Optional[str] = None) -> Optional[Job]:
        """Take the next due job (or exactly `job_id`) for this worker; None if there is nothing to do."""
        now = datetime.now(timezone.utc)
        with self.begin() as conn:
            stmt = select(jobs.c.job_id).where(jobs.c.status == JobStatus.QUEUED.value)
            if job_id:
                stmt = stmt.where(jobs.c.job_id == job_id)
            else:
                stmt = stmt.where(jobs.c.run_after <= ts(now)).order_by(jobs.c.run_after, jobs.c.created_at).limit(1)
            candidate = conn.execute(stmt.with_for_update(skip_locked=True)).scalar()
            if candidate is None:
                return None
            claimed = conn.execute(
                update(jobs)
                .where(jobs.c.job_id == candidate, jobs.c.status == JobStatus.QUEUED.value)
                .values(
                    status=JobStatus.RUNNING.value,
                    locked_by=worker_id,
                    locked_until=ts(now + timedelta(seconds=lease_seconds)),
                    attempts=jobs.c.attempts + 1,
                    started_at=ts(now),
                )
            )
            if claimed.rowcount != 1:
                return None
            return self._get(conn, candidate)

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: float = 60) -> bool:
        """Extend the lease; False if this worker no longer owns the job."""
        with self.begin() as conn:
            renewed = conn.execute(
                update(jobs)
                .where(jobs.c.job_id == job_id, jobs.c.locked_by == worker_id, jobs.c.status == JobStatus.RUNNING.value)
                .values(locked_until=ts(datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)))
            )
            return renewed.rowcount == 1

    def mark_side_effects(self, job_id: str) -> None:
        """Record that the job is about to do something outside WorkFlowOS (it will never be replayed)."""
        with self.begin() as conn:
            conn.execute(update(jobs).where(jobs.c.job_id == job_id).values(side_effects_started=True))

    # ---------------------------------------------------------------- finish

    def _finish(self, conn, job_id: str, worker_id: Optional[str], **values) -> bool:
        stmt = update(jobs).where(jobs.c.job_id == job_id, jobs.c.status == JobStatus.RUNNING.value)
        if worker_id is not None:
            stmt = stmt.where(jobs.c.locked_by == worker_id)
        terminal = values.get("status") != JobStatus.QUEUED.value
        if terminal:
            values.setdefault("finished_at", ts())
            values["dedupe_key"] = None
        values.update(locked_by=None, locked_until=None)
        return conn.execute(stmt.values(**values)).rowcount == 1

    def complete(self, job_id: str, worker_id: str, result: Optional[Dict[str, Any]] = None) -> bool:
        with self.begin() as conn:
            return self._finish(conn, job_id, worker_id, status=JobStatus.SUCCEEDED.value, result=result, last_error=None)

    def fail(self, job_id: str, worker_id: str, error: str, transient: bool) -> Optional[JobStatus]:
        """Record a handler failure. Returns the job's new status (None if it was no longer ours)."""
        with self.begin() as conn:
            job = self._get(conn, job_id)
            if job is None or job.status != JobStatus.RUNNING:
                return None
            status = self._failure_status(job, transient)
            values: Dict[str, Any] = {"status": status.value, "last_error": error[:2000]}
            if status == JobStatus.QUEUED:
                values["run_after"] = ts(datetime.now(timezone.utc) + timedelta(seconds=self.backoff(job.attempts)))
            return status if self._finish(conn, job_id, worker_id, **values) else None

    @staticmethod
    def backoff(attempts: int) -> float:
        return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2 ** max(0, attempts - 1))

    @staticmethod
    def _failure_status(job: Job, transient: bool) -> JobStatus:
        if job.side_effects_started:
            return JobStatus.NEEDS_ATTENTION
        if transient and job.attempts < job.max_attempts:
            return JobStatus.QUEUED
        return JobStatus.FAILED

    def recover_expired(self) -> List[Job]:
        """Handle running jobs whose worker stopped renewing the lease. Returns the jobs changed."""
        now = ts()
        changed: List[Job] = []
        with self.begin() as conn:
            stale = conn.execute(
                select(jobs)
                .where(jobs.c.status == JobStatus.RUNNING.value, jobs.c.locked_until < now)
                .with_for_update(skip_locked=True)
            ).all()
            for row in stale:
                job = _job(row)
                status = self._failure_status(job, transient=True)
                message = (
                    "The worker stopped while this job was changing external systems. Check them, then dismiss."
                    if status == JobStatus.NEEDS_ATTENTION
                    else "The worker stopped before finishing; the job was retried."
                    if status == JobStatus.QUEUED
                    else "The worker stopped before finishing, and no attempts are left."
                )
                if self._finish(conn, job.job_id, None, status=status.value, last_error=message, run_after=now):
                    changed.append(self._get(conn, job.job_id))
        for job in changed:
            logger.warning("Recovered job %s (%s) after its lease expired: %s", job.job_id, job.kind, job.status.value)
        return changed

    def dismiss(self, job_id: str, actor: str) -> Optional[Job]:
        """Close a job that needs attention (or failed) after a person has dealt with it."""
        with self.begin() as conn:
            done = conn.execute(
                update(jobs)
                .where(
                    jobs.c.job_id == job_id,
                    jobs.c.status.in_([JobStatus.NEEDS_ATTENTION.value, JobStatus.FAILED.value]),
                )
                .values(
                    status=JobStatus.DISMISSED.value,
                    last_error=func.coalesce(jobs.c.last_error, "") + f" (dismissed by {actor})",
                )
            )
            return self._get(conn, job_id) if done.rowcount == 1 else None

    # ----------------------------------------------------------------- reads

    def _get(self, conn, job_id: str) -> Optional[Job]:
        row = conn.execute(select(jobs).where(jobs.c.job_id == job_id)).first()
        return _job(row) if row else None

    def get(self, job_id: str) -> Optional[Job]:
        with self.connect() as conn:
            return self._get(conn, job_id)

    def list(self, statuses: Optional[List[JobStatus]] = None, kind: Optional[str] = None, limit: int = 100) -> List[Job]:
        stmt = select(jobs)
        if statuses:
            stmt = stmt.where(jobs.c.status.in_([s.value for s in statuses]))
        if kind:
            stmt = stmt.where(jobs.c.kind == kind)
        with self.connect() as conn:
            return [_job(r) for r in conn.execute(stmt.order_by(jobs.c.created_at.desc()).limit(limit))]

    def has_active(self, dedupe_key: str) -> bool:
        stmt = select(jobs.c.job_id).where(
            jobs.c.dedupe_key == dedupe_key, jobs.c.status.in_([s.value for s in ACTIVE_JOB_STATUSES])
        )
        with self.connect() as conn:
            return conn.execute(stmt).first() is not None
