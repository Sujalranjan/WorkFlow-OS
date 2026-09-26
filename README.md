# WorkFlowOS

WorkFlowOS is an AI-powered desktop workflow automation system designed to observe routine digital tasks, identify repetitive patterns, understand user intent, generate structured workflows, obtain user approval, and execute workflows using the most reliable available mechanisms.

> **Current Status**: Phase 12 (Real Gmail API Integration — Read-Only Search) completed. Implements the first real external execution integration in WorkFlowOS using the Gmail API. **Phase 12 implements one read-only Gmail API operation (`search_email`)**. WorkFlowOS does NOT fully automate Gmail: zero state mutations are supported (no email sending, deleting, archiving, moving, labeling, mark-as-read, or arbitrary attachment downloading). Execution is deterministically routed via `StrategySelector` (`API_INTEGRATION` &rarr; `GmailApiExecutor`), enforced by `ExecutionPolicyEngine` (mandatory human approval, strict parameter validation), authenticated using official Google OAuth 2.0 with the narrowest scope (`https://www.googleapis.com/auth/gmail.readonly`), and protected against credential leakage. Results are normalized (`GmailSearchResult`, `GmailMessageSummary`), deterministically verified by `GmailVerificationStrategy`, recorded in `ExecutionAuditRecord`, and consumed by Phase 11 `LearningEngine`. Demonstrates safe fail-closed behavior (`AUTHENTICATION_REQUIRED`, `INTEGRATION_UNAVAILABLE`) with zero fallback to local executors. Passes 153/153 automated tests.

---

## Repository Structure

```
WorkFlowOS/
├── backend/          # FastAPI backend, SQLite, Discovery, DNA, SemanticEngine, CanonicalRepository, ExecutionEngine, VerificationEngine, StrategySelector, LearningEngine, GmailClient, & GmailApiExecutor
├── desktop-agent/    # Desktop activity agent, Windows collectors, queue, & demo scripts (demo_phase8.py ... demo_phase12.py)
├── frontend/         # React + TypeScript UI with Canonical Specification, Approval, Execution Plan, Verification, Strategy Selection, Learning View, & Gmail Integration Status
├── workflows/        # Canonical workflow schema definitions
├── docs/             # Architecture and development documentation
├── tests/            # Automated test suite (153 automated tests across all phases)
├── .env.example      # Configuration template
├── .gitignore        # Git ignore rules
└── README.md         # Project documentation
```

---

## Quickstart

### 1. Backend Service
```bash
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```
- Health endpoint: `http://127.0.0.1:8000/health`
- Events endpoint: `http://127.0.0.1:8000/api/events`
- Discovery endpoint: `http://127.0.0.1:8000/api/discovery/candidates`
- Workflow DNA endpoint: `http://127.0.0.1:8000/api/workflows/dna`
- Semantic Interpretation: `POST http://127.0.0.1:8000/api/workflows/{dna_id}/interpret`
- Canonical Specification Creation: `POST http://127.0.0.1:8000/api/workflows/{semantic_workflow_id}/specification`
- Approval endpoint: `POST http://127.0.0.1:8000/api/workflows/specifications/{workflow_id}/approve`
- Execution Plan Creation: `POST http://127.0.0.1:8000/api/workflows/specifications/{workflow_id}/execution-plan`
- Strategy Info for Plan: `GET http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}/strategy`
- Strategy Info for Execution: `GET http://127.0.0.1:8000/api/workflows/executions/{execution_id}/strategy`
- Execute Approved Plan: `POST http://127.0.0.1:8000/api/workflows/execution-plans/{execution_plan_id}/execute`
- Verification Trigger: `POST http://127.0.0.1:8000/api/workflows/executions/{execution_id}/verify`
- Latest Verification for Execution: `GET http://127.0.0.1:8000/api/workflows/executions/{execution_id}/verification`
- Specific Verification Run: `GET http://127.0.0.1:8000/api/workflows/verifications/{verification_run_id}`
- Workflow Learning Profile: `GET http://127.0.0.1:8000/api/workflows/{workflow_id}/learning`
- Workflow Learning Events: `GET http://127.0.0.1:8000/api/workflows/{workflow_id}/learning/events`
- Refresh Workflow Learning: `POST http://127.0.0.1:8000/api/workflows/{workflow_id}/learning/refresh`

### 2. Desktop Agent & Phase 12 / 12.1 Real Gmail API Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"

# Run complete dual-path demo (Path A safe block + Path B live test)
python desktop-agent/desktop_agent/demo_phase12.py

# Or run the dedicated live Gmail verification runner
python desktop-agent/desktop_agent/demo_phase12_live.py --query "from:me"
```
*(Demonstrates Path A: safe unauthenticated block with zero mutations and zero fallback, and Path B: real Gmail read when credentials exist or clean graceful skip).*

For Phase 11 learning demo:
```bash
python desktop-agent/desktop_agent/demo_phase11.py
```

### 3. Frontend Dashboard
```bash
cd frontend
npm install
npm run dev
```

### 4. Running Tests
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
pytest tests/ -v
```

For more details on architecture and development, refer to:
- [docs/architecture.md](file:///e:/WorkFlow%20OS/docs/architecture.md)
- [docs/development.md](file:///e:/WorkFlow%20OS/docs/development.md)

