# Development guide

How to run WorkFlowOS from source, connect the integrations, and run the tests. For running everything in containers, see the Docker section of the [README](../README.md).

## Prerequisites

- Python 3.12 (3.10+ works)
- Node.js 22 with npm
- Windows for live desktop observation (the window collector uses Win32 APIs); the backend, frontend and tests run on any OS

## Services

| Service | Command (from the repo root) | URL |
|---|---|---|
| API | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend` | http://127.0.0.1:8000/docs |
| Demo CRM | `python backend/app/crm_server.py` | http://127.0.0.1:8001/ui/customers |
| Dashboard | `cd frontend && npm install && npm run dev` | http://localhost:5173 |

Install the Python dependencies once:

```bash
pip install -r backend/requirements.txt -r desktop-agent/requirements.txt
```

The full API reference (every endpoint, with request and response schemas) is the interactive OpenAPI page at `/docs`.

## Configuration

Copy `.env.example` to `.env`. Real environment variables override `.env`. Every setting is optional; without an integration the related steps stop safely with a clear reason instead of running.

### Gemini

- `GEMINI_API_KEY`: Google AI Studio key. Without it, routines are described by the built-in rule-based interpreter.
- `GEMINI_MODEL`: a model your key can access.

Gemini is called with JSON output and a response schema, and its result is checked against the observed routine and the action catalog before it is used.

### Gmail (read-only)

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project and enable the **Gmail API**.
2. Configure the **OAuth consent screen** (External), add the scope `https://www.googleapis.com/auth/gmail.readonly`, and add your Google account under **Test users**.
3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app**, download it and save it as `credentials.json` in the repo root.
4. Set `GMAIL_ENABLED=true` and sign in:

   ```bash
   python scripts/gmail_login.py
   ```

   This opens Google's consent page, saves `token.json`, and confirms access with one read-only search. Use `--force` to replace an expired sign-in. While the OAuth app is in *Testing* mode, Google expires the sign-in after 7 days.

`credentials.json` and `token.json` are git-ignored. WorkFlowOS only ever requests the read-only scope; it cannot send, delete, label or move mail.

### Slack

Create a Slack app with a bot token that has `chat:write` (and `channels:history` for verification), invite the bot to your channel, and set `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID`. Notifications always go to `SLACK_CHANNEL_ID`.

### CRM

`CRM_API_BASE_URL` points at the CRM REST API (default: the bundled Demo CRM on port 8001). `CRM_WEB_BASE_URL` is the CRM's browser address, used to recognise CRM pages in observed activity.

### Logging

`LOG_FORMAT=text` (default locally) or `json` (one object per line, the default in Docker). Every API request gets an id, returned in the `X-Request-ID` header and attached to all log lines written while handling it. `LOG_LEVEL` sets the level.

## Recording activity

- **Desktop agent** (window focus and file events):

  ```bash
  # PowerShell
  $env:PYTHONPATH=".;backend;desktop-agent"
  python -m desktop_agent.agent
  ```

  Settings: `ENABLE_REAL_COLLECTION`, `WINDOW_POLL_INTERVAL`, `WINDOW_DEBOUNCE_SECONDS`, `FILE_WATCH_DIRECTORY`, `BACKEND_API_URL`.

- **Browser extension** (Gmail searches and downloads, CRM pages and updates, Slack sends): open `chrome://extensions`, enable Developer mode, choose *Load unpacked* and select `desktop-agent/browser_extension`. Its options page sets the backend URL. It never reads email bodies, attachment contents or message text.

Do the routine a few times with a couple of minutes between attempts; the Activity page then lists it under *Repeated routines*.

## Tests

```bash
# PowerShell: $env:PYTHONPATH=".;backend;desktop-agent"
python -m pytest tests -q
```

Tests use throwaway databases and strip secrets, so they never touch your data or live services. Tests that call real Gemini, Slack or Gmail are marked `live` and run only with `WORKFLOWOS_LIVE_TESTS=1`.

Frontend type-check and production build:

```bash
cd frontend && npm run build
```

CI runs both, then builds and starts the Docker stack, on every push and pull request.
