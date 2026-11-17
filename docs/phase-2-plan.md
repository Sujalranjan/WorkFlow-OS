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

### 2b: Migrations
- Alembic in `backend/migrations/`, baseline revision = today's schema.
- `python -m app.cli db upgrade`; the Docker API container runs it on start (before uvicorn).
- Remove every `CREATE TABLE IF NOT EXISTS`; a test asserts models and migrations agree
  (`alembic check`).

### 2c: Postgres in Docker + moving existing data
- `postgres:16` service with a named volume and healthcheck; API and worker wait for it.
- `python -m app.cli db import-sqlite /data/workflowos.db`: copies every table (including the
  encrypted credentials, so Gmail stays connected; the Fernet key is unchanged) into Postgres,
  idempotent, with row counts printed and checked.
- README: backup/restore (`pg_dump`), and keeping `WORKFLOWOS_SECRET_KEY`/key file backed up
  separately.

### 2d: Job queue and worker
- `jobs` table: id, kind, payload, status (`queued/running/succeeded/failed/needs_attention`),
  attempts, run_after, locked_by, locked_until (lease), last_error, timestamps.
- Worker loop: claim one job with `SKIP LOCKED`, renew the lease while running, release on finish;
  graceful shutdown (finish the current job on SIGTERM); expired leases are requeued only if the
  job had not reached an external mutation (decision 5).
- Job kinds: `execute_plan`, `verify_execution`, `approve_run` (execute + verify + learn),
  `poll_triggers` (scheduled, de-duplicated: at most one queued at a time).
- API: execute/approve/verify return `202 Accepted` with a job id; `GET /api/jobs/{id}`;
  the dashboard polls run/execution status (already shows statuses).
- The in-process `TriggerScheduler` is removed; the worker schedules polls.
- Execution engine records "first external mutation started" per run so the retry rule is
  enforceable.

### 2e: Event-loop safety
- Turn blocking `async def` endpoints into plain `def` (FastAPI runs them in a thread pool), or
  enqueue them (verify). Add a test that no `async def` route calls a known-blocking client.

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
