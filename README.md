# WorkFlowOS

WorkFlowOS is an AI-powered desktop workflow automation system designed to observe routine digital tasks, identify repetitive patterns, understand user intent, generate structured workflows, obtain user approval, and execute workflows using the most reliable available mechanisms.

> **Current Status**: Phase 5 (Semantic Understanding & Intent Translation) completed. Evidence-grounded LLM translation of deterministic Workflow DNA into validated `SemanticWorkflow` representations, deterministic semantic validation layer, Gemini provider abstraction with safe offline fallback, comparative frontend view, and 35 deterministic passing tests.

---

## Repository Structure

```
WorkFlowOS/
├── backend/          # FastAPI backend, SQLite, Discovery, WorkflowDNAExtractor, & SemanticUnderstandingEngine
├── desktop-agent/    # Desktop activity agent, Windows collectors, queue, & demo scripts
├── frontend/         # React + TypeScript user interface with Comparative Semantic View
├── workflows/        # Canonical workflow schema definitions
├── docs/             # Architecture and development documentation
├── tests/            # Automated test suite (35 deterministic tests)
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
- Semantic Interpretation endpoint: `POST http://127.0.0.1:8000/api/workflows/{dna_id}/interpret`

### 2. Desktop Agent & Semantic Understanding Demo
```bash
# Windows PowerShell
$env:PYTHONPATH=".;backend;desktop-agent"
python desktop-agent/desktop_agent/demo_phase5.py
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
