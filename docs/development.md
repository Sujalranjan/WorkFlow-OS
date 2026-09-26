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
- Semantic Interpretation API: `POST http://127.0.0.1:8000/api/workflows/{dna_id}/interpret`
- Semantic Workflow Retrieval: `GET http://127.0.0.1:8000/api/workflows/semantic/{semantic_workflow_id}`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

---

## 2. Gemini LLM Configuration (.env)

Phase 5 introduces semantic understanding using Google Gemini:
- `GEMINI_API_KEY`: Your Google AI Studio API key. If unset, the system gracefully operates in offline fallback / mock mode without crashing.
- `GEMINI_MODEL`: Model identifier (default: `gemini-1.5-flash`).

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your-gemini-api-key-here"
```

---

## 3. Desktop Agent (Live Windows Activity Observation)

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

## 4. Running the Demos

### Phase 5: Semantic Understanding & Intent Translation Demo
With the backend running, execute the Phase 5 semantic interpretation demo:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase5.py
```
This script:
1. Ingests a multi-session dataset (3 instances of Customer Replacement Request workflows, developer workflow, and noise).
2. Extracts deterministic Workflow DNA.
3. Invokes `POST /api/workflows/{dna_id}/interpret`.
4. Displays the side-by-side comparison:
   - **Observed Deterministic Ground Truth (WorkflowDNA)**
   - **AI Semantic Interpretation (Validated SemanticWorkflow)** with entity variable mappings (`customer_name` &larr; `window_title_variable_1`) and intent steps.

### Phase 4: Workflow DNA Extraction Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase4.py
```

### Phase 3: Workflow Discovery Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase3.py
```

---

## 5. Frontend Dashboard & Semantic Understanding View

### Install & Run Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

- **Semantic Workflow Interpretation View**:
  - Comparative layout showing **Observed Ground Truth** (left) vs **AI Interpretation** (right).
  - Variable entity mapping cards with confidence indicators (`model_interpretation_confidence: 92% (LLM estimate)`).
  - Step-by-step intent breakdown with citations to DNA evidence.
  - Interactive "Run AI Semantic Interpretation" button with provider toggle (Auto, Mock LLM, Live Gemini).
- **Workflow DNA Analysis**: Structural invariants, variable parameters, optionals, and ordering flow.
- **Discovered Workflow Candidates**: Sequence flow graphs and candidate signatures.
- **Ingested Activity Events**: Real-time event stream.

### Verify Production Build
```bash
npm run build
```

---

## 6. Running Automated Tests

Run the complete deterministic test suite (all 35 tests run offline without requiring external API keys):

```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
pytest tests/ -v
```

### Optional Live Gemini Integration Test
If you have configured `GEMINI_API_KEY`:
```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your-gemini-api-key"
$env:PYTHONPATH=".;backend;desktop-agent"
pytest -k test_live_gemini_provider_integration -v
```
