"""Monitoring: worker heartbeats, readiness, Prometheus metrics and the admin System overview.

- Workers record a heartbeat every few seconds (`service_heartbeats`). A worker not seen for
  WORKER_STALE_SECONDS is reported as down.
- Readiness (`/health/ready`) answers whether this install can do work: database reachable,
  schema at the latest migration, and (when jobs are done by separate workers) a live worker.
- Metrics (`/metrics`, Prometheus text format) are only served with METRICS_TOKEN set, to a caller
  presenting it. They are counts and timings, never names, emails or ids.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select

from app import config
from app.db import Repository, execution_records, jobs, service_heartbeats, upsert, workflow_runs

# ------------------------------------------------------------------ request metrics (per process)

_lock = threading.Lock()
_requests: Dict[Tuple[str, str, str], int] = defaultdict(int)
_durations: Dict[Tuple[str, str], List[float]] = defaultdict(lambda: [0.0, 0])  # sum, count
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_hist: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0] * (len(_BUCKETS) + 1))


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    status_class = f"{status // 100}xx"
    with _lock:
        _requests[(method, route, status_class)] += 1
        d = _durations[(method, route)]
        d[0] += seconds
        d[1] += 1
        h = _hist[(method, route)]
        for i, bound in enumerate(_BUCKETS):
            if seconds <= bound:
                h[i] += 1
        h[-1] += 1  # +Inf


# ------------------------------------------------------------------------- heartbeats


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MonitoringRepository(Repository):
    def heartbeat(self, name: str, kind: str, info: Optional[Dict[str, Any]] = None) -> None:
        with self.begin() as conn:
            upsert(
                conn,
                service_heartbeats,
                {"name": name, "kind": kind, "last_seen": _now().isoformat(), "info": info or {}},
                key=["name"],
            )

    def heartbeats(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(select(service_heartbeats).order_by(service_heartbeats.c.last_seen.desc())).all()
        stale_after = timedelta(seconds=config.WORKER_STALE_SECONDS)
        out = []
        for r in rows:
            seen = datetime.fromisoformat(r.last_seen)
            out.append({"name": r.name, "kind": r.kind, "last_seen": r.last_seen, "alive": _now() - seen < stale_after, "info": r.info})
        return out

    def forget_stale(self, older_than: timedelta = timedelta(days=7)) -> None:
        """Drop heartbeats of workers gone for a long time (restarted containers get new names)."""
        from sqlalchemy import delete

        cutoff = (_now() - older_than).isoformat()
        with self.begin() as conn:
            conn.execute(delete(service_heartbeats).where(service_heartbeats.c.last_seen < cutoff))

    def counts(self, table, column) -> Dict[str, int]:
        with self.connect() as conn:
            return {status: n for status, n in conn.execute(select(column, func.count()).select_from(table).group_by(column))}


# -------------------------------------------------------------------------- readiness


def readiness(repo: Optional[MonitoringRepository] = None) -> Tuple[bool, Dict[str, Any]]:
    repo = repo or MonitoringRepository()
    checks: Dict[str, Any] = {}
    try:
        with repo.connect() as conn:
            conn.execute(select(1))
        checks["database"] = True
    except Exception:  # noqa: BLE001 - reported as not ready
        checks["database"] = False
        return False, checks
    from app import db as dbmod

    if not dbmod.AUTO_CREATE_TABLES:
        try:
            from app import migrate

            checks["migrations"] = migrate.current_revision() == migrate.head_revision()
        except Exception:  # noqa: BLE001
            checks["migrations"] = False
    if not config.EMBEDDED_WORKER:
        checks["worker"] = any(h["alive"] for h in repo.heartbeats() if h["kind"] == "worker")
    return all(v for v in checks.values()), checks


# ----------------------------------------------------------------------------- metrics


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics_text(repo: Optional[MonitoringRepository] = None) -> str:
    repo = repo or MonitoringRepository()
    lines: List[str] = []

    def metric(name: str, kind: str, help_text: str, samples: List[Tuple[Dict[str, str], float]]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            label_text = ",".join(f'{k}="{_esc(str(v))}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_text}}} {value}" if label_text else f"{name} {value}")

    with _lock:
        requests = dict(_requests)
        durations = {k: list(v) for k, v in _durations.items()}
        hist = {k: list(v) for k, v in _hist.items()}
    metric("workflowos_http_requests_total", "counter", "HTTP requests handled by this API process.",
           [({"method": m, "route": r, "status": s}, n) for (m, r, s), n in sorted(requests.items())])
    samples = []
    for (m, r), buckets in sorted(hist.items()):
        for bound, n in zip(_BUCKETS, buckets):
            samples.append(({"method": m, "route": r, "le": str(bound)}, n))
        samples.append(({"method": m, "route": r, "le": "+Inf"}, buckets[-1]))
    lines.append("# HELP workflowos_http_request_duration_seconds Time to handle HTTP requests.")
    lines.append("# TYPE workflowos_http_request_duration_seconds histogram")
    for labels, value in samples:
        lines.append("workflowos_http_request_duration_seconds_bucket{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + f"}} {value}")
    for (m, r), (total, count) in sorted(durations.items()):
        lab = f'method="{_esc(m)}",route="{_esc(r)}"'
        lines.append(f"workflowos_http_request_duration_seconds_sum{{{lab}}} {round(total, 6)}")
        lines.append(f"workflowos_http_request_duration_seconds_count{{{lab}}} {count}")

    metric("workflowos_jobs", "gauge", "Background jobs by status.",
           [({"status": s}, n) for s, n in sorted(repo.counts(jobs, jobs.c.status).items())])
    metric("workflowos_executions", "gauge", "Workflow executions by status.",
           [({"status": s}, n) for s, n in sorted(repo.counts(execution_records, execution_records.c.status).items())])
    metric("workflowos_triggered_runs", "gauge", "Email-triggered runs by status.",
           [({"status": s}, n) for s, n in sorted(repo.counts(workflow_runs, workflow_runs.c.status).items())])
    beats = [h for h in repo.heartbeats() if h["kind"] == "worker"]
    metric("workflowos_workers_alive", "gauge", "Workers seen recently.", [({}, sum(1 for h in beats if h["alive"]))])
    if beats:
        newest = max(datetime.fromisoformat(h["last_seen"]) for h in beats)
        metric("workflowos_worker_last_seen_seconds", "gauge", "Seconds since any worker was last seen.",
               [({}, round((_now() - newest).total_seconds(), 1))])
    ready, _ = readiness(repo)
    metric("workflowos_ready", "gauge", "1 when the install can do work (database, schema, worker).", [({}, 1 if ready else 0)])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- System page


def system_overview(repo: Optional[MonitoringRepository] = None) -> Dict[str, Any]:
    """What an admin needs to see at a glance. No network calls to external services."""
    from app.repositories.automation_repository import AutomationRepository
    from app.services.job_queue import JobQueue, JobStatus

    repo = repo or MonitoringRepository()
    ready, checks = readiness(repo)
    queue = JobQueue()
    attention = queue.list([JobStatus.NEEDS_ATTENTION], limit=20)
    failed_jobs = queue.list([JobStatus.FAILED], limit=10)
    triggers = []
    try:
        for t in AutomationRepository().list_triggers():
            triggers.append({
                "trigger_id": t.trigger_id, "name": t.name, "enabled": t.enabled, "last_polled_at": t.last_polled_at,
                "last_error": t.last_error, "last_note": t.last_note,
            })
    except Exception:  # noqa: BLE001 - shown as empty rather than failing the page
        triggers = []
    return {
        "version": config.VERSION,
        "database": repo.engine.dialect.name,
        "ready": ready,
        "checks": checks,
        "embedded_worker": config.EMBEDDED_WORKER,
        "workers": repo.heartbeats(),
        "jobs": repo.counts(jobs, jobs.c.status),
        "executions": repo.counts(execution_records, execution_records.c.status),
        "triggered_runs": repo.counts(workflow_runs, workflow_runs.c.status),
        "needs_attention": [_job_summary(j) for j in attention],
        "failed_jobs": [_job_summary(j) for j in failed_jobs],
        "triggers": triggers,
        "metrics_enabled": bool(config.METRICS_TOKEN),
        "alerts": _alerts_summary(),
    }


def _job_summary(job) -> Dict[str, Any]:
    return {"job_id": job.job_id, "kind": job.kind, "status": job.status.value, "last_error": job.last_error,
            "created_at": job.created_at, "finished_at": job.finished_at}


def _alerts_summary() -> Dict[str, Any]:
    from app.services.alerts import alert_settings

    channel, pending = alert_settings()
    return {"channel_id": channel, "notify_pending": pending}
