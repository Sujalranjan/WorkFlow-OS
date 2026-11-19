"""Job queue and worker: claiming, leases, retries, and the never-replay-after-side-effects rule.

Runs on SQLite and (on the Postgres leg) on Postgres, where claiming uses FOR UPDATE SKIP LOCKED.
"""

import threading
import time

import httpx
import pytest

from app import db
from app.models.jobs import JobStatus
from app.services import jobs as job_kinds
from app.services.job_queue import JobQueue
from app.worker import Worker


@pytest.fixture
def queue(tmp_path):
    return JobQueue(str(tmp_path / "jobs.db"))


@pytest.fixture
def handlers(monkeypatch):
    """Replace the real handlers with test ones for the duration of a test."""
    table = {}
    monkeypatch.setattr(job_kinds, "HANDLERS", table)
    return table


def test_enqueue_claim_complete(queue):
    job = queue.enqueue("demo", {"x": 1}, created_by="ops")
    assert job.status == JobStatus.QUEUED and job.attempts == 0

    claimed = queue.claim("w1")
    assert claimed.job_id == job.job_id and claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1 and claimed.locked_by == "w1"
    assert queue.claim("w2") is None  # nothing else to do

    assert queue.complete(job.job_id, "w1", {"ok": True})
    done = queue.get(job.job_id)
    assert done.status == JobStatus.SUCCEEDED and done.result == {"ok": True} and done.locked_by is None


def test_delayed_jobs_wait_and_a_worker_cannot_finish_another_workers_job(queue):
    queue.enqueue("later", {}, delay_seconds=3600)
    assert queue.claim("w1") is None

    job = queue.enqueue("now", {})
    queue.claim("w1")
    assert queue.complete(job.job_id, "w2") is False
    assert queue.heartbeat(job.job_id, "w2") is False
    assert queue.heartbeat(job.job_id, "w1") is True


def test_dedupe_key_allows_one_active_job_and_is_freed_when_done(queue):
    first = queue.enqueue("poll", {}, dedupe_key="poll")
    assert queue.enqueue("poll", {}, dedupe_key="poll").job_id == first.job_id
    assert queue.has_active("poll")
    queue.claim("w1")
    queue.complete(first.job_id, "w1")
    assert not queue.has_active("poll")
    assert queue.enqueue("poll", {}, dedupe_key="poll").job_id != first.job_id


def test_transient_failures_retry_with_backoff_then_fail(queue):
    job = queue.enqueue("flaky", {}, max_attempts=2)
    queue.claim("w1")
    assert queue.fail(job.job_id, "w1", "timeout", transient=True) == JobStatus.QUEUED
    retry = queue.get(job.job_id)
    assert retry.run_after > retry.created_at and retry.last_error == "timeout"
    assert queue.claim("w1") is None  # backoff: not due yet

    with queue.begin() as conn:  # make it due now
        conn.execute(db.jobs.update().values(run_after="0"))
    assert queue.claim("w1").attempts == 2
    assert queue.fail(job.job_id, "w1", "timeout again", transient=True) == JobStatus.FAILED


def test_non_transient_failure_does_not_retry(queue):
    job = queue.enqueue("bad", {}, max_attempts=5)
    queue.claim("w1")
    assert queue.fail(job.job_id, "w1", "ValueError: bad input", transient=False) == JobStatus.FAILED


def test_failure_after_side_effects_needs_attention_and_is_never_retried(queue):
    job = queue.enqueue("live", {}, max_attempts=5)
    queue.claim("w1")
    queue.mark_side_effects(job.job_id)
    assert queue.fail(job.job_id, "w1", "Slack timeout", transient=True) == JobStatus.NEEDS_ATTENTION
    assert queue.claim("w1") is None

    dismissed = queue.dismiss(job.job_id, "ops@example.com")
    assert dismissed.status == JobStatus.DISMISSED and "dismissed by ops@example.com" in dismissed.last_error
    assert queue.dismiss(job.job_id, "ops@example.com") is None


def test_expired_lease_requeues_safe_jobs_and_flags_ones_with_side_effects(queue):
    safe = queue.enqueue("read-only", {})
    risky = queue.enqueue("live", {})
    queue.claim("dead-worker", lease_seconds=0.01, job_id=safe.job_id)
    queue.claim("dead-worker", lease_seconds=0.01, job_id=risky.job_id)
    queue.mark_side_effects(risky.job_id)
    time.sleep(0.05)

    recovered = {j.job_id: j.status for j in queue.recover_expired()}
    assert recovered == {safe.job_id: JobStatus.QUEUED, risky.job_id: JobStatus.NEEDS_ATTENTION}
    assert "changing external systems" in queue.get(risky.job_id).last_error
    assert queue.claim("w2").job_id == safe.job_id  # the safe one runs again


def test_each_job_is_claimed_by_exactly_one_worker(queue):
    ids = {queue.enqueue("parallel", {"i": i}).job_id for i in range(20)}
    claimed, lock = [], threading.Lock()

    def work(name):
        while True:
            try:
                job = queue.claim(name)
            except Exception:  # SQLite may report "database is locked" under contention; retry
                time.sleep(0.01)
                continue
            if job is None:
                return
            with lock:
                claimed.append(job.job_id)

    threads = [threading.Thread(target=work, args=(f"w{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(claimed) == sorted(ids)  # every job once, none twice


# ------------------------------------------------------------------- worker


def test_worker_runs_handlers_and_records_results(queue, handlers):
    handlers["ok"] = lambda payload, ctx: {"doubled": payload["n"] * 2}
    handlers["boom"] = lambda payload, ctx: (_ for _ in ()).throw(ValueError("nope"))
    handlers["flaky"] = lambda payload, ctx: (_ for _ in ()).throw(httpx.ConnectError("down"))
    ok = queue.enqueue("ok", {"n": 21})
    boom = queue.enqueue("boom", {})
    flaky = queue.enqueue("flaky", {}, max_attempts=3)
    worker = Worker(queue=queue, worker_id="w", schedule_trigger_polls=False)

    while worker.process():
        pass
    assert queue.get(ok.job_id).result == {"doubled": 42}
    assert queue.get(boom.job_id).status == JobStatus.FAILED and "ValueError: nope" in queue.get(boom.job_id).last_error
    assert queue.get(flaky.job_id).status == JobStatus.QUEUED  # transient: retried later


def test_handler_that_fails_after_side_effects_reports_needs_attention(queue, handlers, monkeypatch):
    seen = []
    monkeypatch.setattr(job_kinds, "on_needs_attention", lambda job: seen.append(job.job_id))

    def live(payload, ctx):
        ctx.side_effects()
        raise httpx.ReadTimeout("slack timed out")

    handlers["live"] = live
    job = queue.enqueue("live", {}, max_attempts=3)
    Worker(queue=queue, worker_id="w", schedule_trigger_polls=False).process()
    assert queue.get(job.job_id).status == JobStatus.NEEDS_ATTENTION and seen == [job.job_id]


def test_worker_renews_its_lease_while_a_job_runs(queue, handlers):
    def slow(payload, ctx):
        time.sleep(2.5)
        return {}

    handlers["slow"] = slow
    job = queue.enqueue("slow", {})
    worker = Worker(queue=queue, worker_id="w", lease_seconds=1.5, schedule_trigger_polls=False)
    done = threading.Thread(target=worker.process)
    done.start()
    time.sleep(2.0)  # past the original lease: without heartbeats another worker would take it over
    assert queue.recover_expired() == []
    done.join(timeout=10)
    assert queue.get(job.job_id).status == JobStatus.SUCCEEDED


def test_worker_schedules_one_email_poll_at_a_time(queue, handlers, monkeypatch):
    handlers[job_kinds.POLL_TRIGGERS] = lambda payload, ctx: {"triggers_polled": 0}
    monkeypatch.setattr("app.config.TRIGGER_POLLER_TICK_SECONDS", 0)
    a = Worker(queue=queue, worker_id="a", schedule_trigger_polls=True)
    b = Worker(queue=queue, worker_id="b", schedule_trigger_polls=True)
    a._maybe_schedule_poll()
    b._maybe_schedule_poll()
    assert len(queue.list(statuses=[JobStatus.QUEUED], kind=job_kinds.POLL_TRIGGERS)) == 1
    assert a.tick() is True
    assert queue.list(kind=job_kinds.POLL_TRIGGERS)[0].status == JobStatus.SUCCEEDED


def test_worker_stops_cleanly(queue, handlers):
    worker = Worker(queue=queue, worker_id="w", poll_interval=0.05, schedule_trigger_polls=False)
    t = threading.Thread(target=worker.run_forever)
    t.start()
    time.sleep(0.2)
    worker.stop()
    t.join(timeout=5)
    assert not t.is_alive()
