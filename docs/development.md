# WorkFlowOS Development Guide

This guide describes how to run, test, and demonstrate the WorkFlowOS system with live collectors and the Phase 3 Workflow Discovery Engine.

---

## Prerequisites

- **OS**: Windows 10/11
- **Python**: Version 3.10+ (tested on Python 3.12)
- **Node.js**: Version 18+ (tested on Node v22)
- **npm**: Version 9+

---

## 1. Backend Setup & Run

### Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### Run Backend Server
From the workspace root:
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```
- Health Check: `http://127.0.0.1:8000/health`
- Event Ingestion API: `http://127.0.0.1:8000/api/events`
- Discovery API: `http://127.0.0.1:8000/api/discovery/candidates`
- Workflow DNA API: `http://127.0.0.1:8000/api/workflows/dna`
- Workflow DNA Item API: `http://127.0.0.1:8000/api/workflows/dna/{dna_id}`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

---

## 2. Desktop Agent (Live Windows Activity Observation)

### Configuration (.env)
You can customize the desktop agent behavior via environment variables:
- `ENABLE_REAL_COLLECTION`: Set to `true` to activate live Windows window and file watchers (`false` for test-only mode).
- `WINDOW_POLL_INTERVAL`: Window focus check frequency in seconds (default `0.5`).
- `WINDOW_DEBOUNCE_SECONDS`: Debounce duration to suppress transient focus flickers (default `0.3`).
- `FILE_WATCH_DIRECTORY`: Directory monitored for file additions/moves (default `watch_folder`).
- `BACKEND_API_URL`: Backend endpoint (default `http://127.0.0.1:8000`).

### Running the Live Desktop Agent
Start the agent with live Windows window focus observation and directory watching:
```bash
# Windows PowerShell
$env:PYTHONPATH="backend;desktop-agent"
python desktop-agent/desktop_agent/agent.py
```

---

## 3. Running the Demos

### Phase 4: Workflow DNA Extraction Demo
With the backend running, execute the deterministic Workflow DNA extraction demo:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase4.py
```
This script:
1. Ingests a multi-session dataset (3 instances of Customer Replacement Request workflows with variable titles, variable invoice filenames, an optional Excel step, a developer workflow, and isolated noise).
2. Hits `GET /api/workflows/dna`.
3. Displays:
   - Core / Invariant Steps (100% occurrence)
   - Variable Parameters & Templates (e.g. `invoice_{variable}.pdf`)
   - Optional Steps (e.g. `Microsoft Excel`, 1/3 sessions)
   - Ordering Constraints (pairwise precedence)
   - Preconditions & Structural Boundaries
   - Explainable Evidence

### Phase 3: Workflow Discovery Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase3.py
```

---

## 4. Frontend Dashboard & Workflow DNA View

### Install & Run Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

- **Workflow DNA Analysis**: Card-based view showing:
  - Invariant steps with checkmarks (✓) and occurrence ratios (3/3)
  - Variable parameters with template patterns (`invoice_{variable}.pdf`) and observed tag clouds
  - Optional steps with bullet indicators (?)
  - Step-by-step ordering precedence flow (`Gmail` &rarr; `File System` &rarr; `CRM` &rarr; `Slack`)
  - Structural preconditions and execution boundaries
  - Plain-language evidence cards
- **Discovered Workflow Candidates**: Sequence flow graphs and candidate signatures.
- **Ingested Activity Events**: Real-time event stream showing recent activity.

### Verify Production Build
```bash
npm run build
```

---

## 5. Running Automated Tests

Run the complete test suite:

```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
pytest tests/ -v
```

All 26 tests across Phase 0, 1, 2, 3, and 4 will run deterministically.
