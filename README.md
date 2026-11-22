# WorkFlowOS

[![CI](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/ci.yml/badge.svg)](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/ci.yml)

WorkFlowOS watches the routine work you do across apps, finds the parts you repeat, turns them into a workflow you approve, and then runs that workflow for you through real integrations (Gmail, a CRM, Slack), with a dry run first. After that, an email trigger queues a run for each new matching email. You approve each run, and a run stops to ask you whenever it can't decide safely (for example, an unknown customer).

```mermaid
flowchart LR
    O[Observe<br/>desktop agent +<br/>browser extension] --> D[Discover<br/>repeated routines]
    D --> I[Interpret<br/>Gemini, checked against<br/>what was observed]
    I --> A{Approve<br/>workflow}
    A --> R[Run<br/>manually or on<br/>new email, approved]
    R --> X[Gmail · CRM · Slack]
    X --> V[Verify<br/>independent re-reads]
    V --> L[Reliability]
```

Details: [docs/architecture.md](docs/architecture.md) · setup and configuration: [docs/development.md](docs/development.md).

## How observation becomes execution

The **Action Catalog** ([backend/app/services/action_catalog.py](backend/app/services/action_catalog.py)) is the fixed list of actions WorkFlowOS can actually perform:

| Catalog action | Observed as | Executor | Risk |
|---|---|---|---|
| `gmail.search_email` | Gmail search route `#search/<query>` | GmailApiExecutor (read-only) | low |
| `gmail.download_attachment` | completed download from Gmail | GmailApiExecutor → sandbox | medium |
| `crm.find_customer` | CRM page `/ui/customers/<id>` or `?q=` | CrmApiExecutor | low |
| `crm.update_customer_record` | CRM form submit (status field) | CrmApiExecutor | high, confirmation required |
| `slack.send_notification` | message sent in `app.slack.com/client/<team>/<channel>` | SlackApiExecutor | medium |

- Events are classified deterministically (URL and metadata rules, with no LLM involved). A classified event becomes a DNA step such as `gmail:search_email` with `catalog_action` set. Its parameters (search query, customer, status, channel) become DNA variables.
- The LLM only describes the workflow. It cannot rename, drop or re-route an executable step: the validator rejects output that omits one, and the spec takes action names and risk levels from the catalog.
- Steps with no catalog match (for example window focus) stay in the spec as context. The plan records them as excluded and never executes them.
- Parameters that changed between observed runs (such as the customer) are **never** filled in from a past run. They come from upstream outputs (`customer_query ← sender of the selected email`) or must be supplied at run time.
- Each step is routed to exactly one named executor. Risk policy, the human approval gate and fail-closed execution still apply: a failed **or blocked** step stops the run.

## Repository layout

```
backend/            FastAPI backend: pipeline services, executors, verifiers, Demo CRM (+ browser UI)
desktop-agent/      Windows window/file collectors, event queue, demo scripts
  browser_extension/  Chrome/Edge extension that reports Gmail/CRM/Slack actions
frontend/           React + TypeScript dashboard (pages/, components/, api.ts)
tests/              pytest suite (isolated: never touches your databases or live services)
docs/               Architecture and development notes
```

## Run with Docker

```bash
docker compose up --build
```

This starts Postgres, the API (http://localhost:8000/docs), the Demo CRM (http://localhost:8001/ui/customers) and the dashboard (http://localhost:5173). WorkFlowOS data is stored in Postgres (`workflowos-pg` volume). The `workflowos-data` volume holds the credential encryption key, the execution sandbox and the Demo CRM.

- Set `POSTGRES_PASSWORD` in `.env` before the first start. Postgres is not exposed outside Docker; the default password is only acceptable on a single-user machine.

- Create the first admin (there is no sign-up page; admins add everyone else in **Settings**):
  ```bash
  docker compose exec api python -m app.cli create-user --email you@example.com --name "Your Name" --role admin
  ```
- Connect Gmail and Slack in **Settings > Integrations** (see [Integrations](#integrations)). Credentials are stored encrypted in the data volume; the encryption key is created there too (`/data/workflowos.secret.key`) unless you set `WORKFLOWOS_SECRET_KEY`.
- Ports already in use? `API_PORT=8010 WEB_PORT=5180 CRM_PORT=8011 docker compose up --build`. The Gmail redirect URI follows `API_PORT` (`http://localhost:8010/api/integrations/gmail/callback`).
- Other settings are read from `.env` if it exists (copy `.env.example`).
- The desktop agent and browser extension run on your machine and report to `http://localhost:8000` as usual.
- **Upgrading an install that stored data in SQLite** (before Postgres was added): start the new version, then copy the old data in once:
  ```bash
  docker compose up -d --build
  docker compose exec api python -m app.cli db import-sqlite /data/workflowos.db
  ```
  The import shows a per-table count and checks that every row arrived. It is safe to run again, and it never overwrites rows already in Postgres. Users, sign-ins and the Gmail/Slack connections carry over, because the encryption key in the data volume stays the same. The old SQLite file is not modified.
- **Backups**: back up the database and the encryption key separately (without the key, saved integrations must be connected again):
  ```bash
  docker compose exec -T postgres pg_dump -U workflowos -Fc workflowos > workflowos-$(date +%F).dump
  docker compose cp api:/data/workflowos.secret.key ./workflowos.secret.key
  ```
  Restore a dump with `docker compose exec -T postgres pg_restore -U workflowos -d workflowos --clean < workflowos-YYYY-MM-DD.dump`.
- Logs are JSON, one object per line, with a `request_id` that is also returned in the `X-Request-ID` response header: `docker compose logs -f api`.

## Run locally


```bash
pip install -r backend/requirements.txt -r desktop-agent/requirements.txt
```

1. **Backend** (port 8000):
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
   ```
2. **Demo CRM** (port 8001, API at `/api/crm`, browser UI at `http://127.0.0.1:8001/ui/customers`):
   ```bash
   python backend/app/crm_server.py
   ```
3. **Frontend**:
   ```bash
   cd frontend && npm install && npm run dev
   ```
4. **First admin** (asks for a password of at least 12 characters), then sign in at http://localhost:5173:
   ```bash
   python backend/app/cli.py create-user --email you@example.com --name "Your Name" --role admin
   ```
5. **Observe real activity.** In **Settings → API keys**, create a key. The agent and extension can only *send* activity with it.
   - Desktop agent (window focus and file events): set `WORKFLOWOS_API_KEY` in `.env`, then `python -m desktop_agent.agent` with `PYTHONPATH=".;backend;desktop-agent"`.
   - Browser extension: open `chrome://extensions`, enable Developer mode, choose *Load unpacked* and pick `desktop-agent/browser_extension`. In its options page, set the backend URL and paste the key.

   Then do the routine by hand a few times (at least 2 sessions, separated by 2+ minutes of inactivity).

No real activity yet? On the **Activity** page, click **Load sample activity** (or call `POST /api/demo/seed-activity` with `{"scenario": "observed_browser_routine"}`). That loads three recorded sessions of a Gmail → CRM → Slack routine.

### Using the dashboard

Open `http://localhost:5173`. The sidebar follows the life of a workflow:

| Page | What you do there |
|---|---|
| **Overview** | See which integrations are connected, a getting-started checklist, and anything waiting for you. |
| **Activity** | See what was recorded. Under *Repeated routines*, click **Create workflow** on a routine (e.g. *Gmail → CRM → Slack, seen 3 times*). |
| **Workflows** | Review each step and what it changes, then **Approve** or **Reject**. An approved workflow can be tried with **Test run** (changes nothing) or run with **Run now**. Its reliability appears after it has run. |
| **Inbox** | Approve emails picked up by a trigger, and answer runs that paused (for example, choose which CRM customer an email is about). |
| **Automations** | Create email triggers that start a workflow when a matching email arrives. |
| **Runs** | Every run, step by step, and whether the result was verified afterwards. |
| **Settings** (admins) | Add people and set their role; create and revoke API keys for the agent and extension. |

**Roles:** *viewers* see everything; *approvers* can also create, approve and run workflows and answer paused runs; *admins* can also manage email triggers, users and API keys. Approvals and runs record who did them.

Without `GEMINI_API_KEY`, routines are described by built-in rules from what was observed; with a key, Gemini writes the description and its output is checked against the observation before use.

### Automate it: email triggers

Once a workflow that starts with a Gmail search is approved, open **Automations** and create an email trigger with a Gmail query (for example `subject:"Customer Replacement Request" has:attachment`).

- While the backend runs, it checks Gmail on the trigger's interval (default 60 s, minimum 30 s; read-only). Every new matching email appears in the **Inbox** as a run waiting for approval. Nothing runs until you approve it.
- **Approve & run** executes the workflow for that exact email: the attachment download uses that email's message id, never "the newest match". The run is then verified and fed into the reliability profile.
- If the CRM has no customer for the sender, or several possible ones, the run **pauses** and asks you to pick the customer. It then continues from that step. **Cancel run** stops it instead.
- **Check now** polls immediately. A trigger only considers emails received after it was created, unless you choose a look-back window.
- API: `/api/automation/triggers` and `/api/automation/runs` (see `/docs`). Polling is scheduled by the worker. Set `TRIGGER_POLLER_ENABLED=false` to turn it off.

### Background jobs and the worker

Slow or external work runs in a background **worker**, not inside web requests: workflow runs, verification, approved email runs and email polling. **Run**, **Check results** and **Approve and run** queue a job and return right away. The dashboard then follows the job until it finishes.

- **Docker:** the `worker` service does this. To run two workers: `docker compose up -d --scale worker=2`. Each job still runs exactly once.
- **Locally:** the API starts a worker thread itself (`EMBEDDED_WORKER=true`, the default), so `uvicorn` alone is enough. To run it separately instead, set `EMBEDDED_WORKER=false` and start `python backend/app/worker.py`.
- **Retries:** a job that fails before it changes anything outside WorkFlowOS is retried with backoff, for example when Gmail or the CRM is briefly unreachable. A live run that may already have updated the CRM or posted to Slack is **never retried automatically**. If it's interrupted (say the worker crashes), it's marked **Needs attention** on the Overview page and in the Inbox. Check the CRM and Slack, then dismiss it.
- **Stopping:** the worker finishes the job in hand before it exits.
- **API:** `GET /api/jobs` and `GET /api/jobs/{job_id}`; `POST /api/jobs/{job_id}/dismiss` (admin).

### Integrations

| Service | Configure | Notes |
|---|---|---|
| Gemini (optional) | `GEMINI_API_KEY`, `GEMINI_MODEL` in `.env` | Without a key an offline deterministic interpreter is used |
| Gmail (read-only) | **Settings > Integrations > Connect Gmail** | See below. Older alternative: `credentials.json` + `python scripts/gmail_login.py` |
| Slack | **Settings > Integrations > Slack** | Bot token (`xoxb-`) with `chat:write` (+ `channels:history` for verification); checked with Slack before saving. `SLACK_BOT_TOKEN`/`SLACK_CHANNEL_ID` still work as a fallback |
| CRM | `CRM_API_BASE_URL`, `CRM_WEB_BASE_URL` | Defaults to the bundled Demo CRM on port 8001 |

**Connecting Gmail** (once per installation):

1. In Google Cloud Console, enable the Gmail API and create an OAuth client ID of type **Web application**.
2. Add the redirect URI shown in Settings as an *authorized redirect URI*: `PUBLIC_API_URL` + `/api/integrations/gmail/callback` (default `http://localhost:8000/api/integrations/gmail/callback`).
3. Paste the client ID and secret into Settings, click **Connect Gmail**, and approve read-only access.

The sign-in uses PKCE and a single-use state that expires after 10 minutes. Only the `gmail.readonly` scope is requested. **Disconnect** revokes the token at Google.

Credentials saved in Settings are encrypted with `WORKFLOWOS_SECRET_KEY`, or with a key file created next to the database. Back up that key separately from the database: without it, saved integrations must be connected again. Settings take precedence over the older `.env` and `token.json` setup. Environment variables take precedence over `.env`. Never commit `.env`, `credentials.json`, `token.json` or `*.secret.key` (they are git-ignored).

## Tests

```bash
# PowerShell: $env:PYTHONPATH=".;backend;desktop-agent"
PYTHONPATH=".;backend;desktop-agent" pytest tests -q
```

To run the same suite on Postgres, point it at a throwaway database. Each test gets its own schema, and the schemas are dropped afterwards:

```bash
docker run -d --name wfos-test-pg -e POSTGRES_USER=wfos -e POSTGRES_PASSWORD=wfos -e POSTGRES_DB=wfos_test -p 127.0.0.1:55432:5432 postgres:16-alpine
WORKFLOWOS_TEST_DATABASE_URL=postgresql+psycopg://wfos:wfos@127.0.0.1:55432/wfos_test PYTHONPATH=".;backend;desktop-agent" pytest tests -q
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the suite on both SQLite and Postgres, type-checks and builds the frontend, and builds and starts the Docker stack on every push and pull request.

Each test session uses a throwaway database, CRM database and sandbox, and strips secrets from the environment. Tests that call real Gemini, Slack or Gmail are marked `live` and skipped unless you opt in with `WORKFLOWOS_LIVE_TESTS=1`.

The observation-to-execution bridge is covered by [tests/backend/test_observed_to_execution.py](tests/backend/test_observed_to_execution.py) and [tests/backend/test_observed_to_execution_api.py](tests/backend/test_observed_to_execution_api.py). They feed recorded browser sessions through the whole pipeline, check that the discovered workflow matches the reference spec in [reference_workflow.py](backend/app/services/reference_workflow.py), and then execute and verify it.

## Database and migrations

WorkFlowOS uses SQLite by default (`DATABASE_PATH`, default `workflowos.db`). Set `DATABASE_URL` to use Postgres instead (`postgresql+psycopg://user:password@host:5432/db`).

The schema is versioned with Alembic migrations in [backend/app/migrations](backend/app/migrations). The API applies them when it starts (`MIGRATE_ON_START=true`, the default). To apply or inspect them by hand:

```bash
python backend/app/cli.py db upgrade   # apply migrations
python backend/app/cli.py db current   # show the schema revision
python backend/app/cli.py db check     # fails if the database and the code's tables differ
```

Databases created before migrations existed are adopted automatically: existing tables and rows are kept, and missing tables and indexes are added.

To change the schema, edit the tables in [backend/app/db.py](backend/app/db.py), then generate a migration and review it before committing:

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
```

## Adding an integration or an action

Each external tool is one module in [backend/app/integrations](backend/app/integrations) (see `gmail.py`, `demo_crm.py`, `slack.py`). The action catalog, the event classifier, the executor and verifier registries, `/api/status` and the dashboard's connection list are all built from these modules.

1. **Actions:** declare a `CatalogAction` for each thing the tool can do. Give it an id `<integration key>.<action>`, its executor's name, a risk level, parameters and outputs.
2. **Recognising it:** write a classifier that recognises the action in observed activity (URL pattern, download source or form submit), returning `None` for anything else.
3. **Doing and checking it:** add factories for the executor, which must declare each action in `supported_actions`, and for a read-only verifier. If later steps need the action's outputs, map them to context keys in `ExecutionEngine`.
4. **Status:** add a status check, which returns whether the tool is connected plus a hint and never credentials. Then add the module to `INTEGRATIONS` in `app/integrations/__init__.py`.
5. **Tests:** add classification and execution tests. `tests/backend/test_integrations_framework.py` then checks the new module automatically: namespaced action ids, exact executor routing, registry membership, and classifiers that don't overlap.

More detail: [docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md).

## License

[MIT](LICENSE)
