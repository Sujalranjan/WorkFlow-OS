# WorkFlowOS

WorkFlowOS is an AI-powered desktop workflow automation system designed to observe routine digital tasks, identify repetitive patterns, understand user intent, generate structured workflows, obtain user approval, and execute workflows using the most reliable available mechanisms.

> **Current Status**: Phase 4 (Workflow DNA) completed. Deterministic extraction of invariant steps, variable parameters with pattern templates, optional steps, pairwise ordering constraints, structural preconditions, boundary metrics, and explainable evidence. Full frontend Workflow DNA dashboard and 26 passing tests.

---

## Repository Structure

```
WorkFlowOS/
├── backend/          # FastAPI backend, SQLite, DiscoveryEngine, & WorkflowDNAExtractor
├── desktop-agent/    # Desktop activity agent, Windows collectors, queue, & demo scripts
├── frontend/         # React + TypeScript user interface, Workflow DNA View, & Event Viewer
├── workflows/        # Canonical workflow schema definitions
├── docs/             # Architecture and development documentation
├── tests/            # Automated test suite (26 deterministic tests)
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

### 2. Desktop Agent & Workflow DNA Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase4.py
```

### 3. Frontend Dashboard
```bash
cd frontend
npm install
npm run dev
```

### 4. Running Tests
```bash
$env:PYTHONPATH=".;backend;desktop-agent"
pytest tests/ -v
```

For more details on architecture and development, refer to:
- [docs/architecture.md](file:///e:/WorkFlow%20OS/docs/architecture.md)
- [docs/development.md](file:///e:/WorkFlow%20OS/docs/development.md)
