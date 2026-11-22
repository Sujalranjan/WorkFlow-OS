# WorkFlowOS

[![CI](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/ci.yml/badge.svg)](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/ci.yml)
[![Security](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/security.yml/badge.svg)](https://github.com/Sujalranjan/WorkFlow-OS/actions/workflows/security.yml)

WorkFlowOS watches the routine work you do across apps, finds the parts you repeat, turns them into a workflow you approve, and then runs that workflow for you through real integrations (Gmail, HubSpot or a demo CRM, Slack, Google Sheets, a shared folder), with a dry run first. After that, an email trigger queues a run for each new matching email. You approve each run, and a run stops to ask you whenever it can't decide safely (for example, an unknown customer).

**Highlights**

- **Learns from observation, not prompts:** a desktop agent and browser extension record structured events; repeated routines are found deterministically and turned into workflows. An LLM only describes them, and its output is validated against what was observed.
- **Safe by construction:** a fixed action catalog is the only path to execution, every workflow (and every edited version) needs human approval, runs fail closed, ambiguous lookups pause for a person, and work that may have changed an external system is never retried automatically.
- **Real integrations, least privilege:** Gmail read-only by default (labeling and Sheets are opt-in permissions), HubSpot, Slack (channel picker, thread replies, Add to Slack), Google Sheets, a shared folder; every action is independently verified after the run.
- **Workflow editor with versioning:** change steps and input sources, checked against the catalog; each save is a new version that must be approved again.
- **Production-ready for one team:** Postgres with migrations, a job queue with leases and workers, HTTPS deployment with Caddy, readiness checks, Prometheus metrics, Slack alerts, backups, security headers, CodeQL and dependency audits. 440+ tests on SQLite and Postgres in CI.

```mermaid
flowchart LR
    O[Observe<br/>desktop agent +<br/>browser extension] --> D[Discover<br/>repeated routines]
    D --> I[Interpret<br/>Gemini, checked against<br/>what was observed]
    I --> A{Approve<br/>workflow}
    A --> R[Run<br/>manually or on<br/>new email, approved]
    R --> X[Gmail · HubSpot / CRM · Slack<br/>Sheets · shared folder]
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
| `gmail.add_label` | label applied in Gmail ("Label as" → Apply) | GmailLabelExecutor (opt-in, adds user labels only) | medium |
| `crm.find_customer` | CRM page `/ui/customers/<id>` or `?q=` | CrmApiExecutor | low |
| `crm.update_customer_record` | CRM form submit (status field) | CrmApiExecutor | high, confirmation required |
| `hubspot.find_contact` | HubSpot contact record page or contacts-list search | HubSpotApiExecutor | low |
| `hubspot.update_contact` | property saved on a HubSpot contact record | HubSpotApiExecutor | high, confirmation required |
| `hubspot.add_note` | note saved on a HubSpot contact record | HubSpotApiExecutor | medium |
| `files.save_to_folder` | file saved into the shared folder the desktop agent watches | SharedFolderExecutor | medium, never overwrites |
| `sheets.append_row` | the same Google Sheet opened in each recorded run | GoogleSheetsExecutor (opt-in, the sheet chosen in Settings) | medium, appends only |
| `slack.send_notification` | message sent in `app.slack.com/client/<team>/<channel>` | SlackApiExecutor | medium |
| `slack.reply_in_thread` | message sent from a thread's reply box | SlackApiExecutor (under this run's own message) | medium |

- Events are classified deterministically (URL and metadata rules, with no LLM involved). A classified event becomes a DNA step such as `gmail:search_email` with `catalog_action` set. Its parameters (search query, customer, status, channel) become DNA variables.
- The LLM only describes the workflow. It cannot rename, drop or re-route an executable step: the validator rejects output that omits one, and the spec takes action names and risk levels from the catalog.
- Steps with no catalog match (for example window focus) stay in the spec as context. The plan records them as excluded and never executes them.
- Parameters that changed between observed runs (such as the customer) are **never** filled in from a past run. They come from upstream outputs (`customer_query ← sender of the selected email`) or must be supplied at run time.
- Each step is routed to exactly one named executor. Risk policy, the human approval gate and fail-closed execution still apply: a failed **or blocked** step stops the run.

## Repository layout

```
backend/            FastAPI backend: pipeline services, executors, verifiers, Demo CRM (+ browser UI)
desktop-agent/      Windows window/file collectors, event queue, demo scripts
  browser_extension/  Chrome/Edge extension that reports Gmail/CRM/HubSpot/Slack actions
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

## Deploy to production

`docker-compose.prod.yml` adds Caddy in front: automatic HTTPS (Let's Encrypt) on your domain, the dashboard and API on one origin, Secure cookies, no other ports published, API docs and `/metrics` not exposed. Readiness (`/health/ready`), Prometheus metrics, a **System** page and Slack alerts cover monitoring; `scripts/backup.sh` / `scripts/restore.sh` handle backups. Step by step: [docs/deployment.md](docs/deployment.md). Security overview: [SECURITY.md](SECURITY.md).

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
| **Workflows** | Review each step and what it changes, then **Approve** or **Reject**. An approved workflow can be tried with **Test run** (changes nothing) or run with **Run now**. Its reliability appears after it has run. **Edit** (approvers) changes the steps and where each input comes from; see below. |
| **Inbox** | Approve emails picked up by a trigger, and answer runs that paused (for example, choose which CRM customer an email is about). |
| **Automations** | Create email triggers that start a workflow when a matching email arrives. |
| **Runs** | Every run, step by step, and whether the result was verified afterwards. |
| **Settings** (admins) | Add people and set their role; create and revoke API keys for the agent and extension. |

### Editing a workflow

On a workflow's page, **Edit** lets an approver remove, reorder or add steps (any catalog action, also one that was never recorded, such as *label the processed email*) and choose where each input comes from: **from an earlier step** of the same run, a **fixed value**, or **ask when the run starts**. The server checks every change against the action catalog as you type: a step cannot come before the step that provides what it needs (for example *reply in thread* before *post to Slack*), and a value that changed between recorded runs (like a customer's email) cannot be fixed to one of those recorded values.

Saving creates a new version (1.0.0 → 1.1.0) with your note and a list of what changed, and sends the workflow back for approval: nothing runs, manually or from an email trigger, until someone approves the new version. Earlier versions are kept in the version history, a reviewer always approves the exact version they looked at, and plans made from an older version can no longer run. Details: [docs/phase-4-plan.md](docs/phase-4-plan.md).

**Roles:** *viewers* see everything; *approvers* can also create, edit, approve and run workflows and answer paused runs; *admins* can also manage email triggers, users and API keys. Approvals and runs record who did them.

Without `GEMINI_API_KEY`, routines are described by built-in rules from what was observed; with a key, Gemini writes the description and its output is checked against the observation before use.

### Automate it: email triggers

Once a workflow that starts with a Gmail search is approved, open **Automations** and create an email trigger with a Gmail query (for example `subject:"Customer Replacement Request" has:attachment`).

- While the backend runs, it checks Gmail on the trigger's interval (default 60 s, minimum 30 s; read-only). Every new matching email appears in the **Inbox** as a run waiting for approval. Nothing runs until you approve it.
- **Approve & run** executes the workflow for that exact email: the attachment download uses that email's message id, never "the newest match". The run is then verified and fed into the reliability profile.
- If the CRM has no customer for the sender, or several possible ones, the run **pauses** and asks you to pick the customer. It then continues from that step. **Cancel run** stops it instead.
- Each check is incremental. Gmail's change log says whether anything arrived since the last check; only then does WorkFlowOS list the matching emails, across every page of results. Up to 50 new emails are queued per check, oldest first, and the rest follow on the next checks, so a burst of emails is never skipped.
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
| Gmail labeling (optional) | **Settings > Integrations > Gmail > Allow labeling**, then **Reconnect Gmail** | Adds the `gmail.modify` permission, used only to *add* labels you created to processed emails. Off by default |
| Google Sheets (optional) | **Settings > Integrations > Gmail > Allow Google Sheets**, then **Reconnect Gmail**, then **Google Sheets**: paste the sheet's link, pick the tab and columns | Adds the `spreadsheets` permission. Each run appends one row (plain text, never formulas) to that one sheet; existing cells are never changed. A workflow recorded with a different sheet is blocked |
| Slack | **Settings > Integrations > Slack** | Bot token (`xoxb-`) with `chat:write` (+ `channels:history` for verification). Add `channels:read` (and `groups:read` for private channels) to pick the channel from a list; without them, type the channel ID. Settings warns when the bot is not in the chosen channel. `SLACK_BOT_TOKEN`/`SLACK_CHANNEL_ID` still work as a fallback. Behind HTTPS you can instead install your team's own Slack app with **Add to Slack** |
| HubSpot | **Settings > Integrations > HubSpot** | Service key with `crm.objects.contacts.read`, `crm.objects.contacts.write`, `crm.schemas.contacts.read`; then choose the contact property that "Update contact" writes. `HUBSPOT_ACCESS_TOKEN` works as a fallback |
| Shared folder | **Settings > Integrations > Shared folder** | A folder on the WorkFlowOS server (with Docker, mount it into the `api` and `worker` containers). `SHARED_FOLDER_PATH` works as a fallback. Set `SHARED_FOLDER_DIRECTORY` for the desktop agent so saving files there is observed |
| CRM | `CRM_API_BASE_URL`, `CRM_WEB_BASE_URL` | Defaults to the bundled Demo CRM on port 8001 |

**Connecting HubSpot:** in HubSpot, create a service key with the three contact scopes above (legacy private apps can no longer be created; an existing private-app token also works) and paste it in Settings. Saving checks the key. Then click **Choose property** to pick the contact property that "Update contact" steps write, and optionally a default value. Adding notes may need the notes scope on some accounts: if HubSpot refuses, the step is reported as blocked with `MISSING_SCOPE` and nothing else changes. Observing HubSpot in the browser is best effort, since HubSpot does not document its page structure; execution uses only the documented API.

**Connecting Gmail** (once per installation):

1. In Google Cloud Console, enable the Gmail API and create an OAuth client ID of type **Web application**.
2. Add the redirect URI shown in Settings as an *authorized redirect URI*: `PUBLIC_API_URL` + `/api/integrations/gmail/callback` (default `http://localhost:8000/api/integrations/gmail/callback`).
3. Paste the client ID and secret into Settings, click **Connect Gmail**, and approve read-only access.

The sign-in uses PKCE and a single-use state that expires after 10 minutes. Only the `gmail.readonly` scope is requested, unless an admin turns on **Allow labeling**: then `gmail.modify` is requested too, and WorkFlowOS uses it only to add user labels (never system labels such as Trash, Spam or Inbox, and never to send, delete, archive or move email). Unticking it on Google's consent screen keeps Gmail read-only; label steps are then blocked with a clear message. **Disconnect** revokes the token at Google.

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

### Live tests (real accounts, off by default)

`python -m pytest tests -q` never calls a real service: secrets and Phase 3 settings are scrubbed from the environment. To check the integrations against real test accounts, set the variables below (in `.env` or the shell) and run with `WORKFLOWOS_LIVE_TESTS=1`. Each test is skipped when its variables are missing, and the live tests only read, except the Slack ones, which post a message and a thread reply to the given channel.

| Test | Variables |
|---|---|
| Slack post, thread reply, channel list | `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID` (a test channel) |
| HubSpot access, contact search, properties | `HUBSPOT_ACCESS_TOKEN`, optional `WORKFLOWOS_LIVE_HUBSPOT_EMAIL` (a contact that exists) |
| Gmail labels and Google Sheets metadata | `WORKFLOWOS_LIVE_GOOGLE_TOKEN` (an authorized-user JSON file granted the opt-in scopes), optional `WORKFLOWOS_LIVE_SHEET_ID` |

```powershell
$env:PYTHONPATH=".;backend;desktop-agent"; $env:WORKFLOWOS_LIVE_TESTS="1"; python -m pytest tests -q -m live
```

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

Each external tool is one module in [backend/app/integrations](backend/app/integrations) (see `gmail.py`, `demo_crm.py`, `hubspot.py`, `files.py`, `google_sheets.py`, `slack.py`). The action catalog, the event classifier, the executor and verifier registries, `/api/status` and the dashboard's connection list are all built from these modules.

1. **Actions:** declare a `CatalogAction` for each thing the tool can do. Give it an id `<integration key>.<action>`, its executor's name, a risk level, parameters and outputs.
2. **Recognising it:** write a classifier that recognises the action in observed activity (URL pattern, download source or form submit), returning `None` for anything else.
3. **Doing and checking it:** add factories for the executor, which must declare each action in `supported_actions`, and for a read-only verifier. If later steps need the action's outputs, map them to context keys in `ExecutionEngine`.
4. **Status:** add a status check, which returns whether the tool is connected plus a hint and never credentials. Then add the module to `INTEGRATIONS` in `app/integrations/__init__.py`.
5. **Settings:** credentials go in the encrypted credential store (`credential_store.py`); non-secret choices (a channel, a property, a folder, a sheet) go in a record's metadata. Add admin-only routes in `api/integrations.py`, list them in `ROUTE_POLICY` (`security.py`), and a card in `frontend/src/pages/SettingsPage.tsx`. A permission that is not always needed is opt-in: request it only after an admin allows it, and block the step (with what to do) until it is granted.
6. **Rules every executor follows:** a dry run makes no external call; missing setup or permission is `BLOCKED` before anything changes; values that differ per run come from upstream outputs (`{message_id}`, `{slack_ts}`), never from a recording; ambiguous lookups return `NEEDS_INPUT`.
7. **Tests:** add classification and execution tests against a fake of the tool's API (see `test_hubspot.py`), plus a recorded routine in `services/observed_sessions.py` that is discovered and run end to end. `tests/backend/test_integrations_framework.py` then checks the new module automatically: namespaced action ids, exact executor routing, registry membership, and classifiers that don't overlap. Tests that need a real account are marked `@pytest.mark.live` (see below).

More detail: [docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md).

## License

[MIT](LICENSE)
