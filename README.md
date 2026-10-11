# WorkFlowOS

WorkFlowOS watches the routine work you do across apps, finds the parts you repeat, turns them into a workflow you approve, and then runs that workflow for you through real integrations (Gmail, a CRM, Slack), with a dry run first.

```
Observe ──► Discover ──► DNA ──► Interpret ──► Spec + approval ──► Plan ──► Execute ──► Verify ──► Learn
(agent +    (repeated    (what    (LLM, checked   (human must        (exact    (Gmail/    (independent  (reliability
 browser     sessions)    stays/   against the     approve)           routing)  CRM/Slack)  re-checks)    profile)
 extension)               varies)  DNA)
```

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
frontend/           React + TypeScript dashboard
tests/              pytest suite (isolated: never touches your databases or live services)
docs/               Architecture and development notes
```

## Quickstart

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
4. **Observe real activity**
   - Desktop agent (window focus and file events): `python -m desktop_agent.agent` with `PYTHONPATH=".;backend;desktop-agent"`.
   - Browser extension: open `chrome://extensions`, enable Developer mode, choose *Load unpacked* and pick `desktop-agent/browser_extension`. Its options page sets the backend URL.

   Then do the routine by hand a few times (at least 2 sessions, separated by 2+ minutes of inactivity).

No real activity yet? In the dashboard, click **⚡ Observed Gmail → CRM → Slack**, or call `POST /api/demo/seed-activity` with `{"scenario": "observed_browser_routine"}`. That loads three recorded sessions. Then go through Discovery → DNA → Interpret → Spec → Approve → Plan → Dry run.

### Integrations

| Service | Configure | Notes |
|---|---|---|
| Gemini (optional) | `GEMINI_API_KEY`, `GEMINI_MODEL` in `.env` | Without a key an offline deterministic interpreter is used |
| Gmail (read-only) | `credentials.json` (OAuth client) + `GMAIL_ENABLED=true` | Sign in: `python desktop-agent/desktop_agent/demo_phase12_live.py` (delete an expired `token.json` first) |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID` | Bot needs `chat:write` (+ `channels:history` for verification) |
| CRM | `CRM_API_BASE_URL`, `CRM_WEB_BASE_URL` | Defaults to the bundled Demo CRM on port 8001 |

Environment variables take precedence over `.env`. Never commit `.env`, `credentials.json` or `token.json` (they are git-ignored).

## Tests

```bash
# PowerShell: $env:PYTHONPATH=".;backend;desktop-agent"
PYTHONPATH=".;backend;desktop-agent" pytest tests -q
```

Each test session uses a throwaway database, CRM database and sandbox, and strips secrets from the environment. Tests that call real Gemini, Slack or Gmail are marked `live` and skipped unless you opt in with `WORKFLOWOS_LIVE_TESTS=1`.

The observation-to-execution bridge is covered by [tests/backend/test_observed_to_execution.py](tests/backend/test_observed_to_execution.py) and [tests/backend/test_observed_to_execution_api.py](tests/backend/test_observed_to_execution_api.py). They feed recorded browser sessions through the whole pipeline, check that the discovered workflow matches the reference spec in [phase16_workflow.py](backend/app/services/phase16_workflow.py), and then execute and verify it.

## Adding a new executable action

1. Add a `CatalogAction` to `ACTION_CATALOG` (executor name, risk, parameters, outputs).
2. Teach `classify_event()` how the action looks when a person does it (URL pattern, download source, form submit).
3. Make sure the executor declares the action in `supported_actions`. If needed, map its outputs to context keys in `ExecutionEngine`.
4. Add a classification test and extend the recorded-session tests.

More detail: [docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md).
