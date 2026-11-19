# Phase 2: Postgres and background workers

Goal: WorkFlowOS keeps working when several people use it at once and when a workflow takes
minutes. Data moves to Postgres with versioned migrations, and slow work (running workflows,
verification, email polling) moves out of HTTP requests into a worker process.

Scope stays "production-ready for one team". No multi-tenancy, no Kubernetes.

## Where things stand

| Area | Today | Problem |
|---|---|---|
| Storage | 10 repositories, raw `sqlite3`, 16 tables, most rows stored as one JSON blob (`record_json`, `spec_json`, ...) | One writer at a time; no migrations (schema is `CREATE TABLE IF NOT EXISTS` in each repository); can't run more than one API process safely |
| Schema changes | none, by design so far | The first column change will need a hand-written migration on every install |
| Running a workflow | `POST .../execute` and run approval execute inside the HTTP request | A slow Gmail/CRM/Slack call holds the request open; a server restart mid-run leaves the run `RUNNING` forever |
| Verification | `POST /executions/{id}/verify` is `async def` but calls Slack/CRM synchronously | Blocks the event loop: the whole API stalls while it waits. 11 other `async def` endpoints do blocking SQLite reads (smaller version of the same bug) |
| Email polling | `TriggerScheduler` asyncio loop inside the API process | Two API processes would poll twice and create duplicate runs |
| Demo CRM | its own SQLite `crm.db` | Fine: it is a stand-in for a real CRM, not part of WorkFlowOS data |

## Decisions (agreed 2026-11-16)

1. **SQLAlchemy 2.0 Core + Alembic**, not the ORM. Repositories keep their shape and their JSON
   documents (`JSONB` on Postgres, `JSON` on SQLite); only the SQL inside them changes. This is
   the smallest change that gives us both databases and migrations, and it keeps the test suite's
   expectations intact.
2. **`DATABASE_URL`** selects the database: `postgresql+psycopg://...` in Docker and production,
   `sqlite:///workflowos.db` stays the default for local dev and tests. `DATABASE_PATH` keeps working
   (mapped to a SQLite URL) so nothing breaks for existing installs.
3. **Job queue in Postgres** (a `jobs` table claimed with `SELECT ... FOR UPDATE SKIP LOCKED`),
   not Redis/Celery. One less service to run and back up, jobs are transactional with the data
   they change, and it is plenty for one team. On SQLite the same table works with a single worker
   (dev only).
4. **Worker process**: `python -m app.worker`, a separate container in Docker Compose. The API only
   enqueues; the worker executes, verifies and polls.
5. **No automatic retry of anything that may have changed the outside world.** A job is retried
   (with backoff) only if it failed before its first external mutation, or failed in a read-only
   step with a transient error (timeout, 5xx, connection). A run interrupted mid-mutation is marked
   `NEEDS_ATTENTION` for a person to inspect, never replayed. This preserves the fail-closed rule.

## Milestones

Each milestone ends with the full test suite green on **both** SQLite and Postgres, and is
mergeable on its own.

### 2a: Database layer (done)
- `app/db.py`: engine from `DATABASE_URL`, connection helper, `JSON`/`JSONB` type, one `MetaData`
  with all 16 tables defined explicitly (columns that are queried today become real columns;
  the rest stay in the JSON document).
- Port the 10 repositories and `credential_store.py` from `sqlite3` to SQLAlchemy Core, one at a
  time, behaviour unchanged. Replace the `:memory:` special case with per-test SQLite files.
- Tests: `WORKFLOWOS_TEST_DATABASE_URL` runs the suite on Postgres (each test database becomes its own
  schema); CI runs it on SQLite and on Postgres via a service container.
- Outcome: all repositories and the credential store use `app/db.py`; existing SQLite files read
  unchanged (verified against a copy of a real install, including decrypting the stored Gmail token);
  fixed along the way: `EventRepository.get_by_id` had no FROM clause, `insert_ignore` now uses
  RETURNING (psycopg reports rowcount -1), OAuth states are consumed with DELETE ... RETURNING.

### 2b: Migrations (done)
- Alembic in `backend/app/migrations/` (inside the package so the Docker image ships it), baseline
  revision `0001` = the 2a schema, written out explicitly so it never changes.
- The baseline adopts pre-migration databases: existing tables and rows are kept, and missing
  tables and indexes are added. Verified on a copy of a real install (rows unchanged, Gmail token
  still decrypts). Downgrading the baseline is refused (it would drop all data).
- The API runs `app.migrate.upgrade()` on start (`MIGRATE_ON_START`, default on); on Postgres a
  migration holds an advisory lock so concurrent starts (API + worker) are safe.
  `python -m app.cli db upgrade|current|check`; user CLI commands migrate first.
- Tables are no longer created at runtime; only the test suite sets `AUTO_CREATE_TABLES`.
  `tests/backend/test_migrations.py` asserts on SQLite and Postgres that migrating an empty
  database matches `app.db` exactly.

### 2c: Postgres in Docker + moving existing data (done)
- `postgres:16-alpine` service (volume `workflowos-pg`, healthcheck, not published to the host);
  the API gets `DATABASE_URL` and waits for it. `SECRET_KEY_PATH` pins the encryption key to the data
  volume. The Demo CRM stays on SQLite.
- `python -m app.cli db import-sqlite /data/workflowos.db` (`app/db_import.py`): migrates the target,
  copies every table present in the source (legacy or current format), skips rows already present
  (re-runnable, never overwrites), moves the Postgres id sequence, then checks that every source key
  is in the target. The source file is only read.
- Rehearsed with a copy of a real install: 32/32 rows copied, re-run copied 0, and the imported Gmail
  connection passed a live read-only access check from Postgres.
- README: upgrade steps, backups with `pg_dump` plus the key file, restore.

### 2d: Job queue and worker (done)
- `jobs` table (migration `0002`) and `services/job_queue.py`: claim with `FOR UPDATE SKIP LOCKED`
  (conditional UPDATE on SQLite), renewable leases, `dedupe_key` (one active email poll), retries
  with exponential backoff for transient errors before any side effect, `side_effects_started` ->
  `needs_attention` (never replayed), `recover_expired()` for dead workers, `dismiss`.
- `services/jobs.py` handlers: `execute_plan`, `verify_execution`, `execute_run`, `resume_run`,
  `poll_triggers`. Live runs are queued with `max_attempts=1`.
- `app/worker.py`: `python -m app.worker`; heartbeat thread; schedules polls; graceful SIGTERM.
  `EmbeddedWorker` runs inside the API for local development (`EMBEDDED_WORKER`). The in-process
  `TriggerScheduler` is gone. Docker: `worker` service, API has `EMBEDDED_WORKER=false`.
- API: execute and verify return `202` with a job (validation such as approval and policy still
  happens in the request, so bad requests still fail at once). Approving or resuming a run claims it
  in the request (so a double-click still gets 409) and queues the execution. `GET /api/jobs[/{id}]`,
  `POST /api/jobs/{id}/dismiss`. `RunStatus.NEEDS_ATTENTION`.
- Dashboard follows jobs (`waitForJob`, `waitForRun`). Interrupted runs show in the Inbox; jobs that
  need attention show on the Overview page, where an admin can dismiss them.
- Found and fixed during the Docker rehearsal: the events and canonical-spec APIs passed
  `DATABASE_PATH` explicitly, so with `DATABASE_URL` set (Postgres) they wrote to an empty SQLite
  file. This was a 2c bug; a test now forbids `DATABASE_PATH` outside `config.py`/`db.py`.
  Postgres engines now have a 10 s connect timeout, so an unreachable database fails fast instead
  of hanging.

### 2e: Event-loop safety (done)
- The 11 `async def` endpoints in `api/execution.py` that did blocking database reads are now
  plain `def`, so FastAPI runs them in its thread pool. Verify, the one that called Slack and the CRM,
  had already moved to the worker in 2d.
- The CRM form handler (`crm_ui.customer_update`) must stay `async` to read the body; its database
  write now runs in the thread pool.
- `tests/backend/test_event_loop.py`: no WorkFlowOS endpoint may be `async` unless allow-listed, and
  three requests that each wait 1s must finish together (the old code took 3.0s, one after another).

### 2f: CI and docs
- CI: Postgres service; migrations applied from empty; suite on both databases; Docker job starts
  `postgres`, `api`, `worker`, `crm`, `web` and checks that an enqueued dry run completes.
- `docs/architecture.md` and README updated; `.env.example` gains `DATABASE_URL`, worker settings.

## Risks and how they are handled

| Risk | Mitigation |
|---|---|
| Duplicate Slack posts / CRM updates on retry | Decision 5 + existing idempotency keys on executions |
| Losing the Gmail connection when switching databases | Import copies `integration_credentials` ciphertext as-is; key unchanged; tested end to end |
| SQLite vs Postgres behaviour drift (types, case sensitivity, timestamps) | Suite runs on both in CI; timestamps stay ISO-8601 UTC strings as today |
| Stuck runs after a crash | Leases + `NEEDS_ATTENTION` status visible in the dashboard |
| Breaking existing installs | SQLite remains supported; `DATABASE_PATH` still honoured; migrations idempotent |

## Out of scope (later phases)

Gmail push notifications instead of polling, HubSpot/Slack OAuth, more catalog actions (Phase 3);
workflow editor (Phase 4); hosting, TLS, monitoring and alerting (Phase 5).
