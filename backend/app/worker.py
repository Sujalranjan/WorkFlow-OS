"""Background worker: runs queued jobs and schedules email polling.

    python -m app.worker            # from backend/ (Docker: the `worker` service)

Several workers can run at once on Postgres; each job goes to exactly one of them. The API can also
run a worker thread in-process (EMBEDDED_WORKER, default on for local development) so a single
`uvicorn` command is enough; Docker turns that off and runs this as its own container.

Stopping (Ctrl+C / SIGTERM) finishes the job in hand first.
"""

import logging
import os
import signal
import socket
import sys
import threading
import time
from typing import Optional
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402
from app.models.jobs import JobStatus  # noqa: E402
from app.services import jobs as job_kinds  # noqa: E402
from app.services.job_queue import JobQueue  # noqa: E402

logger = logging.getLogger("workflowos.worker")


class Worker:
    def __init__(
        self,
        queue: Optional[JobQueue] = None,
        worker_id: Optional[str] = None,
        lease_seconds: Optional[float] = None,
        poll_interval: Optional[float] = None,
        schedule_trigger_polls: Optional[bool] = None,
    ) -> None:
        self.queue = queue or JobQueue()
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.lease_seconds = lease_seconds or config.WORKER_LEASE_SECONDS
        self.poll_interval = poll_interval or config.WORKER_POLL_SECONDS
        self.schedule_trigger_polls = (
            config.TRIGGER_POLLER_ENABLED if schedule_trigger_polls is None else schedule_trigger_polls
        )
        self._last_poll_scheduled = 0.0
        self.stop_event = threading.Event()

    # --------------------------------------------------------------- one job

    def process(self, job_id: Optional[str] = None) -> bool:
        """Claim and run one job (the next due one, or exactly `job_id`). Returns False if none was claimed."""
        job = self.queue.claim(self.worker_id, self.lease_seconds, job_id=job_id)
        if job is None:
            return False
        handler = job_kinds.HANDLERS.get(job.kind)
        if handler is None:
            self.queue.fail(job.job_id, self.worker_id, f"Unknown job kind '{job.kind}'.", transient=False)
            return True

        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(job.job_id, stop_heartbeat), daemon=True)
        heartbeat.start()
        ctx = job_kinds.JobContext(job=job, queue=self.queue)
        try:
            result = handler(job.payload, ctx)
        except Exception as e:  # noqa: BLE001 - every failure is recorded on the job
            transient = isinstance(e, job_kinds.TRANSIENT_ERRORS)
            logger.warning("Job %s (%s) failed: %s", job.job_id, job.kind, e)
            status = self.queue.fail(job.job_id, self.worker_id, f"{type(e).__name__}: {e}", transient=transient)
            if status == JobStatus.NEEDS_ATTENTION:
                job_kinds.on_needs_attention(self.queue.get(job.job_id))
        else:
            self.queue.complete(job.job_id, self.worker_id, result)
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=5)
        return True

    def _heartbeat(self, job_id: str, stop: threading.Event) -> None:
        interval = max(1.0, self.lease_seconds / 3)
        while not stop.wait(interval):
            try:
                if not self.queue.heartbeat(job_id, self.worker_id, self.lease_seconds):
                    logger.error("Lost the lease on job %s", job_id)
                    return
            except Exception:  # noqa: BLE001 - a missed heartbeat is retried next interval
                logger.exception("Heartbeat for job %s failed", job_id)

    # ------------------------------------------------------------------ loop

    def tick(self) -> bool:
        """One round: recover abandoned jobs, schedule polling, run one job. True if a job ran."""
        for job in self.queue.recover_expired():
            if job.status == JobStatus.NEEDS_ATTENTION:
                job_kinds.on_needs_attention(job)
        self._maybe_schedule_poll()
        return self.process()

    def _maybe_schedule_poll(self) -> None:
        if not self.schedule_trigger_polls:
            return
        now = time.monotonic()
        if now - self._last_poll_scheduled < config.TRIGGER_POLLER_TICK_SECONDS:
            return
        self._last_poll_scheduled = now
        # At most one poll queued or running at a time, however many workers there are.
        self.queue.enqueue(job_kinds.POLL_TRIGGERS, {}, created_by="scheduler", max_attempts=1, dedupe_key=job_kinds.POLL_TRIGGERS)

    def run_forever(self) -> None:
        logger.info("Worker %s started", self.worker_id)
        while not self.stop_event.is_set():
            try:
                worked = self.tick()
            except Exception:  # noqa: BLE001 - e.g. the database restarting; try again shortly
                logger.exception("Worker tick failed")
                worked = False
            if not worked:
                self.stop_event.wait(self.poll_interval)
        logger.info("Worker %s stopped", self.worker_id)

    def stop(self) -> None:
        self.stop_event.set()


class EmbeddedWorker:
    """A worker thread inside the API process (local development)."""

    def __init__(self) -> None:
        self.worker = Worker()
        self.thread = threading.Thread(target=self.worker.run_forever, name="workflowos-worker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self, timeout: float = 30) -> None:
        self.worker.stop()
        self.thread.join(timeout=timeout)


def main() -> int:
    from app.logging_config import setup_logging
    from app.migrate import upgrade

    setup_logging("worker")
    upgrade()
    worker = Worker()

    def _stop(signum, _frame):
        logger.info("Received signal %s: finishing the current job, then stopping", signum)
        worker.stop()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
