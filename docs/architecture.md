# WorkFlowOS Architecture: Workflow DNA & Discovery

## Overview

WorkFlowOS is an AI-powered desktop workflow automation system designed to observe user digital activity, detect repetition, understand user intent, generate structured workflows, obtain user approval, and execute workflows using the most reliable available mechanisms.

This document describes the architectural flow from raw events to **Workflow Discovery (Phase 3)** and **Workflow DNA (Phase 4)**.

---

## Architectural Progression

```
Phase 3 answers:   "What repeats?"
Phase 4 answers:   "What stays the same and what changes?"
Phase 5+ answers:  "What does it mean?"
```

---

## End-to-End Workflow Pipeline

```
Stored ActivityEvents (SQLite activity_events table)
           ↓
   WorkflowSegmenter
   ├── Chronological event sorting
   ├── Inactivity boundary enforcement (default threshold: 120s)
   └── Maximum session duration enforcement
           ↓
   TaskSession Instances
   ├── session_id (deterministic hash)
   ├── start_time & end_time
   ├── applications_involved & event_count
   └── segmentation_reason (explainable trigger)
           ↓
   WorkflowDiscoveryEngine (Phase 3: "What repeats?")
   ├── Signature Normalization (app:event_type token mapping)
   ├── Noise Suppression (filters incidental background interruptions)
   ├── Deterministic Sequence Clustering (LCS ratio >= 0.65)
   └── Frequency Thresholding (min_occurrences >= 2)
           ↓
   DiscoveryCandidate Instances
   ├── candidate_id (deterministic hash) & normalized_signature
   ├── occurrences count & average_similarity_score
   ├── representative_sequence (ordered NormalizedSteps)
   ├── supporting_session_ids (provenance trail)
   └── explainable evidence text
           ↓
   WorkflowDNAExtractor (Phase 4: "What stays the same and what changes?")
           ↓
┌────────────────────────────────────────────────────────┐
│ WORKFLOW DNA                                           │
├────────────────────────────────────────────────────────┤
│ • Invariant Steps (100% session occurrence)            │
│ • Variable Parameters (observed values, templates)     │
│ • Optional Steps (sub-100% session occurrence)         │
│ • Ordering Constraints (pairwise before/after rules)   │
│ • Preconditions (structural prerequisite flow)         │
│ • Boundaries (first/last step, min/avg/max duration)   │
│ • Evidence (mathematical provenance across all facets) │
└────────────────────────────────────────────────────────┘
           ↓
   FastAPI Endpoints:
   • GET /api/discovery/candidates
   • GET /api/workflows/dna
   • GET /api/workflows/dna/{dna_id}
           ↓
   Frontend React Dashboard:
   • Workflow DNA Analysis View
   • Discovered Workflow Candidates View
   • Live Activity Event Stream
```

---

## Workflow DNA Components

### 1. Invariant Steps
- Steps that occur across 100% of supporting sessions.
- Supported by measurable evidence: occurrence count, total sessions, occurrence ratio (1.0).
- Example: `Gmail` window focus, `File System` download, `CRM` window focus, `Slack` notification.

### 2. Variable Parameters
- Identified by analyzing event metadata across supporting sessions where surrounding event structure remains stable.
- Sources: `window_title`, `file_name`, `url`.
- Candidate names remain structural (`window_title_variable_1`, `file_name_variable_1`) rather than inventing semantic names (e.g. `customer_name`), which will be performed in Phase 5 AI intent understanding.
- Pattern templates are derived deterministically:
  - `invoice_101.pdf`, `invoice_102.pdf`, `invoice_103.pdf` $\rightarrow$ `invoice_{variable}.pdf`
  - `Rahul - Replacement Request`, `Ananya - Replacement Request` $\rightarrow$ `{variable} - Replacement Request`

### 3. Optional Steps
- Steps that appear in a subset ($< 100\%$) of supporting sessions while belonging to the discovered workflow cluster.
- Example: `Microsoft Excel` logging performed in 1 of 3 executions.
- Records occurrence count, total sessions, occurrence ratio, and supporting session IDs.

### 4. Ordering Constraints
- Deterministic pairwise precedence matrix between invariant steps.
- If Step A precedes Step B in 100% of sessions, an explicit ordering constraint is generated:
  - `'gmail:window_focused' consistently occurs before 'file system:file_downloaded'`
  - `'file system:file_downloaded' consistently occurs before 'crm:window_focused'`
  - `'crm:window_focused' consistently occurs before 'slack:window_focused'`

### 5. Preconditions & Boundaries
- Structural entry preconditions: workflow begins with the first invariant step.
- Sequential prerequisite assertions: each step must be preceded by its predecessor.
- Boundaries capture structural start/end steps and exact minimum, maximum, and average durations from supporting sessions.

### 6. Explainable Evidence
- Every DNA dimension produces plain-language, mathematically backed evidence describing the supporting session count, occurrence ratios, observed values, and consistency metrics.

---

## Security & Privacy Boundary

Phase 4 preserves all previous security principles:
- **Zero AI / LLM Calls**: 100% deterministic local computation; no external APIs, cloud models, or third-party inference endpoints are touched.
- **Local Metadata Only**: Only reads captured event metadata (window titles, filenames, URLs); never inspects file contents or desktop pixels.
- **Explainability**: Full transparency into why any parameter or step was classified as invariant, variable, or optional.

---

## What is NOT Implemented Yet
- Semantic AI intent translation (translating `window_title_variable_1` into `customer_name`) — *Phase 5*.
- Executable workflow generation (Playwright, API script generation).
- Dry-run execution & user approval modal.
- Active workflow automation & orchestration.

