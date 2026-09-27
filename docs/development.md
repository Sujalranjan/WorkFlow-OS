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
- Canonical Specification Creation: `POST http://127.0.0.1:8000/api/workflows/{semantic_workflow_id}/specification`
- Canonical Specification Approval: `POST http://127.0.0.1:8000/api/workflows/specifications/{workflow_id}/approve`
- Execution Plan Creation: `POST http://127.0.0.1:8000/api/workflows/specifications/{workflow_id}/execution-plan`
- Execution Plans List: `GET http://127.0.0.1:8000/api/workflows/execution-plans`
- Execution Plan Retrieval: `GET http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}`
- Execution Plan Strategy Details: `GET http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}/strategy`
- Dry Run Simulation: `POST http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}/dry-run`
- Execute Approved Plan: `POST http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}/execute`
- List Execution Audit Records: `GET http://127.0.0.1:8000/api/workflows/executions`
- Get Execution Audit Record: `GET http://127.0.0.1:8000/api/workflows/executions/{execution_id}`
- Get Execution Strategy Details: `GET http://127.0.0.1:8000/api/workflows/executions/{execution_id}/strategy`
- Cancel Execution: `POST http://127.0.0.1:8000/api/workflows/executions/{execution_id}/cancel`
- Trigger Verification: `POST http://127.0.0.1:8000/api/workflows/executions/{execution_id}/verify`
- Get Latest Verification: `GET http://127.0.0.1:8000/api/workflows/executions/{execution_id}/verification`
- Get Verification by Run ID: `GET http://127.0.0.1:8000/api/workflows/verifications/{verification_run_id}`
- Get Workflow Learning Profile: `GET http://127.0.0.1:8000/api/workflows/{workflow_id}/learning`
- Get Workflow Learning Events: `GET http://127.0.0.1:8000/api/workflows/{workflow_id}/learning/events`
- Refresh Workflow Learning: `POST http://127.0.0.1:8000/api/workflows/{workflow_id}/learning/refresh`
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

---

## 3. Gmail API Configuration (.env) & Google Cloud Setup

Phase 12 and 12.1 introduce the first real external service integration: read-only Gmail search.
> **Important**: Phase 12/12.1 implements one read-only Gmail API operation (`search_email`). WorkFlowOS does not fully automate Gmail (zero mutations: no email sending, deleting, archiving, moving, labeling, mark-as-read, or attachment downloads).

### Google Cloud Setup Prerequisites
1. **Create/Select Project**: Navigate to the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. **Enable Gmail API**: Under **APIs & Services** &rarr; **Library**, search for **Gmail API** and click **Enable**.
3. **Configure OAuth Consent Screen**:
   - User Type: **External** (or Internal for Google Workspace domains).
   - App Name: `WorkFlowOS`.
   - Developer contact email: your email address.
   - Scopes: Add `https://www.googleapis.com/auth/gmail.readonly` (read-only access).
   - Test Users: Add your personal/testing Google account email address.
4. **Create OAuth 2.0 Client ID**:
   - Go to **APIs & Services** &rarr; **Credentials** &rarr; **Create Credentials** &rarr; **OAuth client ID**.
   - Application Type: **Desktop app**.
   - Name: `WorkFlowOS Desktop Client`.
   - Download the generated JSON file and save it in the project root as `credentials.json`.
5. **Local Authentication**:
   - When you run `python desktop-agent/desktop_agent/demo_phase12_live.py` (or `demo_phase12.py`), the client automatically starts a local web server, opens your default browser for Google sign-in, and securely stores the authorized token at `token.json`.
   - Both `credentials.json` and `token.json` are strictly protected in `.gitignore`.

### Environment Configuration
- `GMAIL_ENABLED`: Set to `true` to enable Gmail integration (default `false`).
- `GMAIL_CREDENTIALS_PATH`: Path to client secret JSON (default `credentials.json`).
- `GMAIL_TOKEN_PATH`: Path to authorized user token (default `token.json`).
- `GMAIL_SEARCH_QUERY`: Default search filter string (default `from:me`).
- `GMAIL_MAX_RESULTS`: Maximum metadata records to retrieve (default `5`, max `50`).
- **OAuth Scope**: Strictly locked to `https://www.googleapis.com/auth/gmail.readonly` (minimum required read-only scope).

If credentials or tokens are missing, the system fails closed with `AUTHENTICATION_REQUIRED` or `INTEGRATION_UNAVAILABLE`. No fallback to local executors is ever permitted.

---

## 4. Desktop Agent (Live Windows Activity Observation)

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

## 5. Running the Workflow Discovery & Canonical Demos

### Phase 6: Canonical Specification, Risk Analysis & User Approval Demo
With the backend running, execute the Phase 6 canonical specification and governance demo:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase6.py
```
This script demonstrates:
1. Ingestion of multi-session workflow activity.
2. Extraction of deterministic WorkflowDNA.
3. Generation of validated SemanticWorkflow intent.
4. Construction of formal `CanonicalWorkflowSpec` fusing DNA constraints and semantic intent.
5. Parameter binding with deterministic type inference (filenames, identifiers, strings).
6. Customization of parameter semantic names while preserving immutable source parameters.
7. Step-by-step explainable risk analysis (`read_only`, `local_change`, `external_change`, `communication`).
8. Human approval lifecycle (`requires_review` → `approved`) and proof that approval stops safely without autonomous execution.

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

## 6. Frontend Dashboard & Semantic Understanding View

### Install & Run Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

- **Verification & Evidence View (Phase 9)**:
  - Interactive "Verify Execution" button to trigger deterministic post-execution verification.
  - Per-step comparative card breakdown: Action name, Executor Result, Verification Check, and Final Step State (`VERIFIED`, `VERIFICATION_FAILED`, `EXECUTED_UNVERIFIED`, `NOT_APPLICABLE`).
  - Expected State vs Actual Observed State side-by-side inspection.
  - Cryptographic integrity evidence display using SHA-256 (hash, byte size, verified sandbox path).
- **Execution Plan View**: Parameter resolution, strategy assignments, risk indicators, and dry run simulation.
- **Semantic Workflow Interpretation View**: Comparative layout showing **Observed Ground Truth** (left) vs **AI Interpretation** (right).
- **Workflow DNA Analysis**: Structural invariants, variable parameters, optionals, and ordering flow.
- **Discovered Workflow Candidates**: Sequence flow graphs and candidate signatures.
- **Ingested Activity Events**: Real-time event stream.

### Verify Production Build
```bash
npm run build
```

---

## 7. Running Automated Tests

Run the complete deterministic test suite (all 153 tests run offline using mocks without requiring external credentials):

```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
pytest tests/ -v
```

---

## 8. Running Phase Demos

### Phase 12 / 12.1: Real Gmail API Integration Demo (Read-Only Search)
Run the complete Phase 12 dual-path demo:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase12.py
```
This script demonstrates:
1. **Path A (Safe Non-Authenticated Test)**:
   - Configures an approved workflow with a `search_email` step targeted at Gmail.
   - StrategySelector selects `API_INTEGRATION` &rarr; `GmailApiExecutor`.
   - ExecutionPolicyEngine approves execution.
   - `GmailApiExecutor` detects missing OAuth credentials/tokens and safely blocks execution with status `BLOCKED` and error code `AUTHENTICATION_REQUIRED`.
   - Proves zero fallback to local executor, zero fake success, zero credential leakage, and zero mutations.
2. **Path B (Real Gmail Read Test)**:
   - Evaluates if valid `credentials.json` and `token.json` are present. If `credentials.json` exists without a token, initiates local browser OAuth 2.0 flow.
   - If present: performs live query execution, extracts normalized summaries (`GmailSearchResult`), runs deterministic verification (`GmailVerificationStrategy`), writes `ExecutionAuditRecord`, and refreshes learning profile (`LearningEngine`).
   - If credentials are not present: gracefully skips live invocation and logs clear informational notice without faking data or failing.

To run the dedicated live Gmail verification runner directly:
```bash
# Run with default query (from:me)
python desktop-agent/desktop_agent/demo_phase12_live.py

# Or specify a custom query and max results:
python desktop-agent/desktop_agent/demo_phase12_live.py --query "subject:invoice" --max-results 5
```

### Phase 11: Workflow Learning & Reliability Intelligence Demo
Run the Phase 11 demo demonstrating historical aggregation, failure classification, and advisory suggestions:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase11.py
```
This script demonstrates:
1. Assembly and approval of a CanonicalWorkflowSpec.
2. Multiple execution runs (verified local action, verification failure mismatch, and unsupported external strategy block).
3. Deterministic Learning Engine refresh aggregating execution and verification evidence.
4. Numerical workflow-level reliability metrics (total runs, verified runs, failures, blocked, reliability rate).
5. Step-level empirical reliability breakdown.
6. Empirical pattern discovery (`REPEATED_UNSUPPORTED_STRATEGY`).
7. Advisory improvement suggestions clearly marked `is_advisory = True` and backed by empirical execution/verification IDs.
8. Proof that `CanonicalWorkflowSpec` was NOT mutated by the learning engine.
9. Proof that zero external service calls or mutations occurred (`real_external_mutations = 0`).

### Phase 10: Adaptive Execution & Multi-Strategy Executor Selection Demo
Run the Phase 10 demo demonstrating deterministic executor selection, fallback handling, and safe blocking:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase10.py
```
This script demonstrates:
1. Registration and inspection of all 6 executor capabilities in `ExecutorRegistry`.
2. **Case A (Supported Local Action)**: Deterministically selects `ControlledLocalExecutor` (`CONTROLLED_LOCAL`), validates sandbox containment, executes inside sandbox, and verifies post-execution state (`VERIFIED`).
3. **Case B (Unsupported External Action)**: Evaluates candidates for `send_slack_notification`, discovers all matching strategies (`API_INTEGRATION`, `APPLICATION_INTEGRATION`, `ACCESSIBILITY_UI`, `BROWSER_AUTOMATION`, `UI_FALLBACK`) are architecturally represented but NOT implemented, and deterministically blocks execution with code `UNSUPPORTED_EXECUTION_STRATEGY`.
4. Verification produces `NOT_APPLICABLE` for the blocked run with zero fabricated evidence.
5. Verifies formal proof of zero external service calls: `real_external_mutations = 0`.

### Phase 9: Post-Execution Verification & Evidence Demo
Run the Phase 9 verification demo:
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase9.py
```
This script demonstrates:
1. Assembly and approval of a CanonicalWorkflowSpec.
2. Creation of an ExecutionPlan with concrete parameter bindings.
3. Execution of a safe local action via `ControlledLocalExecutor` inside the sandbox (`workflowos_sandbox/<execution_id>`).
4. Showing `Executor Result: SUCCESS`.
5. Running deterministic verification producing `Verification: VERIFIED`.
6. Inspecting cryptographic integrity evidence using SHA-256.
7. Demonstrating verification failure (`Executor: SUCCESS` + `Verification: FAILED` → `ACTION EXECUTED BUT EXPECTED STATE WAS NOT VERIFIED`).
8. Verifying SQLite persistence across repository retrieval.
9. Confirming zero external service mutations.

### Phase 8: Execution Engine & Controlled Local Execution Demo
With the backend running, run the Phase 8 controlled execution demo:
```bash
# In terminal 1: Start backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend

# In terminal 2: Run Phase 8 demo
python desktop-agent/desktop_agent/demo_phase8.py
```

### Phase 7: Execution Planning & Dry Run Demo
```bash
python desktop-agent/desktop_agent/demo_phase7.py
```
