# WorkFlowOS Architecture: Workflow Discovery, DNA & Semantic Understanding

## Overview

WorkFlowOS is an AI-powered desktop workflow automation system designed to observe user digital activity, detect repetition, understand user intent, generate structured workflows, obtain user approval, and execute workflows using the most reliable available mechanisms.

This document describes the architectural flow from raw events to **Workflow Discovery (Phase 3)**, **Workflow DNA (Phase 4)**, and **Semantic Understanding & Intent Translation (Phase 5)**.

---

## Architectural Progression

```
Phase 3 answers:   "What repeats?"
Phase 4 answers:   "What stays the same and what changes?"
Phase 5 answers:   "What does it mean?"
Phase 6 answers:   "What is the formal workflow contract and how does the human govern it?"
Phase 7+ answers:  "How do we safely execute the approved specification?"
```

---

## End-to-End Workflow Pipeline

```
Raw Activity Events (Windows Window Focus & File Watchers)
           ↓
   WorkflowSegmenter (Temporal & Inactivity Boundaries)
           ↓
   TaskSession Instances (Deterministic Session Hashing)
           ↓
   WorkflowDiscoveryEngine (Noise-tolerant Sequence Clustering)
           ↓
   DiscoveryCandidate Instances (Deterministic Canonical Signatures)
           ↓
   WorkflowDNAExtractor (Empirical Invariants, Variables & Evidence)
           ↓
   Deterministic WorkflowDNA Object
           ↓
   SemanticUnderstandingEngine
           ↓
   Prompt Construction (Structured DNA Context ONLY)
           ↓
   LLM Provider Layer (GeminiSemanticProvider / MockSemanticProvider)
           ↓
   Structured JSON Output
           ↓
   Deterministic Semantic Validation Layer (Ground Truth Enforcement)
           ↓
   Canonical Validated SemanticWorkflow Model
           ↓
   FastAPI Endpoints:
   • GET /api/discovery/candidates
   • GET /api/workflows/dna
   • GET /api/workflows/dna/{dna_id}
   • POST /api/workflows/{dna_id}/interpret
   • GET /api/workflows/semantic/{semantic_workflow_id}
           ↓
   Frontend React Dashboard:
   • Comparative View: Observed Ground Truth vs AI Interpretation
   • Workflow DNA Analysis View
   • Discovered Workflow Candidates View
   • Live Activity Event Stream
```

---

## Why the LLM Receives WorkflowDNA Rather Than Raw Events

A central architectural differentiator of WorkFlowOS is that **raw desktop events are never streamed directly into an LLM**.

1. **Noise Elimination**: Raw desktop streams contain hundreds of irrelevant focus events, accidental clicks, and alt-tabs. Sending raw streams to an LLM leads to hallucinated patterns and prompt bloat.
2. **Deterministic Ground Truth**: Mathematical occurrence ratios, temporal boundaries, and precedence matrices are empirical facts that software computes deterministically. The LLM is an interpreter of facts, not the authority over what occurred.
3. **Strict Privacy**: By boiling thousands of low-level OS events down to an abstract WorkflowDNA signature, sensitive transient desktop data is never transmitted across the network.
4. **Token Efficiency & Speed**: A structured WorkflowDNA object is concise (~500 tokens), enabling sub-second, highly reproducible structured responses.

---

## Semantic Understanding Architecture (Phase 5)

### 1. Provider Abstraction
The semantic layer interacts with LLMs exclusively through the `SemanticModelProvider` abstract base class:
- `GeminiSemanticProvider`: Communicates with Google's Gemini models (`gemini-1.5-flash`) enforcing strict JSON output (`response_mime_type: "application/json"`).
- `MockSemanticProvider`: Deterministic, offline provider used for automated testing, fallback evaluation, and offline local development without API keys.

### 2. Prompt Contract & Strict JSON Schema
The prompt explicitly instructs the LLM:
- **Role**: You are a desktop workflow semantics interpreter.
- **Rules**:
  1. Rely exclusively on the supplied `WorkflowDNA`.
  2. Map semantic steps 1-to-1 to observed invariant step keys (`source_dna_step_key`).
  3. Map semantic variables to observed structural parameters (`source_parameter`).
  4. Preserve ordering constraints.
  5. Never produce executable code, browser automation, or click coordinates.
  6. Label confidence explicitly as `model_interpretation_confidence` (an LLM estimate).

### 3. Deterministic Semantic Validation Layer
Before any LLM response is accepted by the application, the `SemanticWorkflowValidator` verifies:
- **Step Validity**: Every `source_dna_step_key` must exist in the source DNA's invariant or optional steps.
- **Variable Validity**: Every `source_parameter` must match an existing parameter in `dna.variable_parameters`.
- **Application Validity**: The step's application name must match the application in the corresponding DNA step.
- **Ordering Validity**: The sequence of semantic steps must not contradict any pairwise ordering constraints established in DNA.
- **No Invented Actions**: Reject any output containing hallucinated steps or applications.

If validation fails, the response is rejected and diagnostic errors are returned. The system never silently repairs hallucinated output.

### 4. Safe Fallback Behavior
If the Gemini API key is missing, network is down, or an error occurs:
- The backend does **not** crash.
- Returns an `InterpretationResponse` with `status: "fallback"`.
- The deterministic `WorkflowDNA` is preserved and returned completely intact.
- The UI clearly indicates that semantic interpretation is currently unavailable.

---

## Security & Privacy Boundary

- **What is sent to LLM**: ONLY abstract metadata enclosed in `WorkflowDNA` (application names, high-level event types, observed window title prefixes/suffixes, and duration metrics).
- **What is NEVER sent to LLM**: Zero screenshots, zero desktop pixels, zero keystrokes, zero clipboard data, zero passwords, zero document/file bodies, and zero browser HTML.

---

---

## Phase 6: Canonical Specification, Parameter Binding & Human Governance

### 1. Why `CanonicalWorkflowSpec` Exists
A common failure mode in AI-powered workflow systems is conflating an LLM's natural-language summary with an authoritative workflow specification.
- **WorkflowDNA**: Empirical, mathematical ground truth extracted deterministically from multi-session event logs (invariant actions, variable template ratios, ordering precedence, empirical durations).
- **SemanticWorkflow**: Human-understandable semantic translation proposed by an LLM (what the routine means, why steps exist, estimated confidence).
- **CanonicalWorkflowSpec**: The formal, auditable workflow contract. It fuses deterministic DNA boundaries with validated semantic intent, explicitly binds variables to typed schemas, performs deterministic risk assessments, and tracks human approval.

### 2. Parameter Binding & Deterministic Type Inference
Dynamic parameters in recurring routines change values across sessions (e.g. customer names, ticket IDs, downloaded files).
- **Independent Parameter Traceability**: Distinct DNA parameters are never merged even if the LLM proposes identical semantic names (e.g. `window_title_variable_1` and `window_title_variable_3` both mapped to `customer_name` remain two distinct parameter bindings).
- **Deterministic Type Inference**: Variable types (`string`, `filename`, `application`, `identifier`, `timestamp`, `unknown`) are inferred strictly from metadata evidence without LLM hallucination.
- **User Customization**: Users can edit semantic names (e.g., `customer_name` → `client_account_name`). The underlying DNA `source_parameter` remains completely immutable.

### 3. Explainable Risk Analysis
Every workflow step is deterministically classified to establish the degree of human confirmation required:
- `read_only` (LOW): Window observation, inspection, viewing records.
- `local_change` (MEDIUM): Local filesystem downloads, saving files to disk.
- `external_change` (HIGH): Mutating records in external CRM, ERP, or database systems.
- `communication` (MEDIUM): Broadcasting team notifications via Slack, Teams, or email.
- `potentially_sensitive` (HIGH): Involving credentials, API tokens, or confidential personal data.

Every classification carries an explicit human-readable `reason`.

### 4. Human Approval Lifecycle State Machine
New workflow specifications always initialize to `requires_review` (or `draft`). The system **never** automatically approves a workflow.
- **Approval Transition**: `requires_review` → `approved`.
- **Rejection Transition**: `requires_review` → `rejected` (with reason).
- **Safety Rule**: **Approval confirms specification intent ONLY**. Approval does NOT trigger Playwright, Selenium, PyAutoGUI, API calls, or shell execution. Execution is strictly deferred to future phases.

### 5. Complete End-to-End Traceability
A judge or auditor can query any step in the canonical specification and inspect its complete lineage:
`CanonicalStep` → `source_semantic_step_id` → `source_dna_step_key` → `evidence_reference` → `TaskSession` → `ActivityEvent`.

---

---

## Phase 7: Execution Planning & Dry Run (Shadow Mode)

Phase 7 builds the layer that converts an **APPROVED** `CanonicalWorkflowSpec` into a deterministic `ExecutionPlan` and simulates what WorkFlowOS WOULD do, without actually performing any external or desktop action.

### 1. Distinction Between Stages

| Concept | Purpose | Mutates System? |
|---|---|---|
| **Canonical Workflow Specification** | Formal contract of invariant steps, parameters, boundaries, and governance approval. | NO |
| **Execution Plan** | Concrete plan resolving runtime parameters, execution strategies, and expected state transitions. | NO |
| **Dry Run / Shadow Simulation** | Deterministic walk-through validating plan execution, verifying parameters, and reporting `SIMULATED`. | NO (0 real actions) |
| **Actual Execution (Phase 8+)** | Real OS, browser, or API mutation. | **NOT IMPLEMENTED IN PHASE 7** |

### 2. Strategy Selection with Explainable Rationale
Execution strategies are selected deterministically with human-auditable reasons:
- `application_integration`: External CRM/ERP mutations requiring rollback safeguards.
- `api`: Direct service webhooks (e.g. Slack announcements).
- `browser_automation`: Web browser interactions (Chrome, Edge).
- `accessibility_semantic_ui`: OS semantic UI tree automation.
- `ui_fallback`: Computer vision fallback when semantic UI trees are unavailable.

*Note: Strategies are planned abstractions only in Phase 7; no execution engine is invoked.*

### 3. State Change Separation
For every step, the system contrasts:
- `before_state`: System state prior to step.
- `expected_after_state`: Expected outcome of the step.
- `actual_state`: Strictly preserved as `UNTOUCHED (Simulation Mode - No Real Actions Executed)`.

### 4. Deterministic Parameter Resolution
- Distinguishes parameter definition, observed sample values, runtime values, and unresolved status.
- Strict anti-hallucination guarantee: The LLM is never allowed to invent runtime values. Missing required values mark the step as `UNRESOLVED` and block the simulation.

---

## Phase 8: Execution Engine Foundation & Controlled Local Execution

Phase 8 introduces the first real execution layer while maintaining strict security boundaries, fail-closed guardrails, and complete auditability.

### 1. Execution Pipeline Architecture

```
Approved CanonicalWorkflowSpec
          ↓
    ExecutionPlan
          ↓
   Execution Policy (Guardrails)
          ↓
   Executor Registry (Discovery)
          ↓
Controlled Local Executor (Sandbox)
          ↓
   Execution Result (Per-Step)
          ↓
     Audit Record (SQLite)
```

### 2. Core Execution Principles & Guardrails

1. **Human Approval Enforcement (Fail-Closed)**:
   - Live execution requires the source `CanonicalWorkflowSpec` to be in `ApprovalState.APPROVED`.
   - Specifications in `requires_review` or `rejected` states are immediately rejected with HTTP 400 Bad Request before any executor is invoked.

2. **Execution Policy Engine (`ExecutionPolicyEngine`)**:
   - Evaluates security policies before plan execution and before each step.
   - Rejects unapproved workflows and unresolvable required parameters.
   - Detects external mutations (`external_change`, `communication`) and blocks them safely, ensuring external services (CRM, Slack, Gmail) remain completely untouched.

3. **Executor Abstraction (`BaseExecutor`) & Registry (`ExecutorRegistry`)**:
   - Decouples execution orchestration from concrete strategy engines via an abstract interface: `supports(strategy)`, `validate(step, context)`, and `execute(step, context)`.
   - The `ExecutorRegistry` manages available executors and dispatches steps dynamically.

4. **Controlled Local Sandbox Executor (`ControlledLocalExecutor`)**:
   - Executes safe local actions strictly within a designated sandbox root directory (`workflowos_sandbox/<execution_id>`).
   - **Path Traversal Protection**: Any path containing `..` or resolving outside the sandbox root is strictly rejected.
   - **Allowlisted Actions Only**: Permits `save_file`, `create_file`, `read_file`, `copy_file`, `generate_report`.
   - **Prohibited Capabilities**: Strictly blocks shell execution (`bash`, `sh`, `cmd`, `powershell`), process spawning (`subprocess`, `exec`, `eval`), arbitrary code evaluation, network sockets/HTTP requests, and external service mutations.

5. **Dry Run vs. Live Controlled Execution**:
   - `DRY_RUN` mode: Simulates step execution through the executor, verifying parameters and guardrails without writing any files to disk.
   - `LIVE` mode: Executes allowlisted operations inside the sandbox directory and records affected artifacts.

6. **Immutable Audit Trail (`ExecutionAuditRecord`)**:
   - Every execution run generates an immutable audit record in SQLite (`workflowos.db` table `execution_records`).
   - Captures `execution_id`, `workflow_id`, `workflow_version`, `execution_plan_id`, `approval_state`, `approved_by`, `execution_mode`, `status`, `start_time`, `end_time`, `step_results`, `affected_resources`, `error_summary`, and `idempotency_key`.
   - Survives backend restarts.

7. **Idempotency Protection**:
   - Supports client-provided idempotency keys to prevent duplicate executions of identical requests.

---

## Phase 9: Post-Execution Verification & Evidence Engine

Phase 9 establishes a deterministic post-execution verification layer that checks whether an executed workflow step actually produced its expected state or result.

```
ExecutionPlan
      ↓
ExecutionEngine
      ↓
Executor (ControlledLocalExecutor)
      ↓
Actual Action (Sandbox File Output)
      ↓
Verification Engine (VerificationEngine)
      ↓
Verification Strategies (FileSystem, StructuredOutput)
      ↓
Verification Checks & Tamper-Proof Evidence (SHA256, Size, Path)
      ↓
Verification Result (Aggregated Status)
      ↓
Execution Audit Record Update (SQLite)
```

### 1. Distinction: Executor Success vs. Verification Success

WorkFlowOS strictly separates action performance from outcome verification:
- **Executor Success**: Only reports whether the executor completed its invocation without an unhandled exception.
- **Verification Success**: Deterministically checks whether the required state change actually occurred in the physical sandbox.
- **Step Outcome States**:
  - `EXECUTED` + `VERIFIED` → **`VERIFIED`**
  - `EXECUTED` + `FAILED` → **`VERIFICATION_FAILED`** (e.g. action reported success, but target file is missing, empty, or corrupted)
  - `EXECUTED` + `UNKNOWN` → **`EXECUTED_UNVERIFIED`** (no deterministic local strategy available)
  - `SKIPPED` / `BLOCKED` → **`NOT_APPLICABLE`**

The system **never** equates executor `SUCCESS` with verification `VERIFIED`, and **never** converts `UNKNOWN` into `VERIFIED`.

### 2. Zero-LLM Deterministic Verification

In accordance with strict safety principles, **Gemini / LLMs are NEVER used to evaluate execution success**:
- AI is restricted to semantic understanding and intent translation (Phase 5).
- Planning, execution policy, execution, and verification are 100% deterministic code.
- This prevents the LLM from grading its own execution results.

### 3. Verification Strategies

1. **`FileSystemVerificationStrategy`**:
   - `file_exists`: Verifies target file exists inside the sandbox.
   - `non_empty_file`: Verifies file size is strictly greater than zero.
   - `directory_exists`: Verifies target folder exists.
   - Computes cryptographic SHA256 hash, byte size, and path metadata as tamper-proof evidence.
2. **`StructuredOutputVerificationStrategy`**:
   - Evaluates JSON payloads inside sandbox files.
   - Deterministically compares expected key-value pairs against actual content.
   - Records matched fields, mismatched fields, and missing properties without AI hallucination.
3. **`ResourceExistenceVerificationStrategy`**:
   - Validates declared affected resources exist in the sandbox.

### 4. Deterministic Evidence Generation

Every verification check generates verifiable, tamper-proof evidence:
```json
{
  "path": "E:\\WorkFlow OS\\workflowos_sandbox\\exec-123\\customer_replacement_summary.json",
  "target_filename": "customer_replacement_summary.json",
  "exists": true,
  "is_file": true,
  "size_bytes": 424,
  "sha256": "afbc0949662a4aba801c188cf6aa2ec0fc431b1685ab458e00792eab06e09dc4",
  "checked_at": "2026-09-26T09:43:49.177416+00:00"
}
```
**Privacy & Security Boundaries**:
- No screenshots or desktop capture.
- No clipboard inspection.
- No password or credential inspection.

### 5. Workflow-Level Verification Aggregation Rules

Deterministic aggregation:
1. If any required check is `FAILED` → Overall **`FAILED`** (`VERIFICATION_FAILED`).
2. Else if any required check is `UNKNOWN` → Overall **`UNKNOWN`** (`EXECUTED_UNVERIFIED`).
3. Else if at least one check is `VERIFIED` → Overall **`VERIFIED`**.
4. If all checks are `NOT_APPLICABLE` → Overall **`NOT_APPLICABLE`**.

### 6. Sandbox Security & Fail-Closed Guardrails

- **Strict Sandbox Boundary**: Verification targets must resolve strictly inside `workflowos_sandbox/<execution_id>`.
- **Path Traversal Rejection**: Paths containing `..` or escaping sandbox are immediately rejected as `FAILED`.
- **Origin Enforcement**: Targets originate only from the approved `ExecutionPlan` or `ExecutionStepResult`. Arbitrary paths provided by clients are forbidden.
- **External Service Prohibition**: Verification of Gmail, CRM, or Slack APIs is explicitly prohibited and marked `NOT_APPLICABLE`.

### 7. Idempotency & Persistence

- **Idempotency**: Calling `POST /verify` without `force_recheck=True` reuses the existing cached `VerificationResult` from SQLite without re-running checks.
- **Persistence**: Results are stored in SQLite (`workflowos.db` tables `workflow_verifications` and `verification_checks`), surviving server restarts.

---

## Phase 10: Adaptive Execution & Multi-Strategy Executor Selection

### 1. Conceptual Distinction: Strategy vs Executor vs Capability vs Fallback

WorkFlowOS maintains strict architectural boundaries between execution concepts:
- **Strategy (`ExecutionStrategyType`)**: An abstract category or paradigm of execution (e.g., direct API integration, application integration, accessibility UI, browser automation, or controlled local sandbox).
- **Executor (`WorkflowExecutor`)**: A concrete execution class (e.g., `ControlledLocalExecutor`, `ApiIntegrationExecutor`) registered in the `ExecutorRegistry`.
- **Capability (`ExecutorCapability`)**: Metadata declared by an executor describing what actions it supports, what target systems it can address, what risk levels it is allowed to handle, whether it is implemented in this phase, whether it requires external network access, and its fallback selection priority.
- **Fallback**: The deterministic ordering through which WorkFlowOS evaluates candidate executors when the preferred mechanism is unavailable or unsupported.

### 2. Supported vs Architecturally Represented Execution Strategies

Phase 10 formally models 6 execution strategies while strictly enforcing implementation realities:

| Strategy | Enum Value | Implementation Status | Executor Class | External Access | Priority |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Controlled Local** | `CONTROLLED_LOCAL` | **IMPLEMENTED** | `ControlledLocalExecutor` | No | 10 |
| **API Integration** | `API_INTEGRATION` | *Architecturally Represented* | `ApiIntegrationExecutor` | Yes | 1 |
| **Application Integration**| `APPLICATION_INTEGRATION` | *Architecturally Represented* | `ApplicationIntegrationExecutor` | Yes | 2 |
| **Accessibility UI** | `ACCESSIBILITY_UI` | *Architecturally Represented* | `AccessibilityUiExecutor` | No | 3 |
| **Browser Automation** | `BROWSER_AUTOMATION` | *Architecturally Represented* | `BrowserAutomationExecutor` | Yes | 4 |
| **UI Fallback** | `UI_FALLBACK` | *Architecturally Represented* | `UiFallbackExecutor` | No | 5 |

**Critical Architectural Invariant**:
Executors with `implemented = False` can be evaluated and surfaced as candidates, but they are **never** invoked. The system never fakes or mocks live external service mutations.

### 3. Deterministic Strategy Selection Algorithm

The `StrategySelector` operates deterministically without LLMs or non-deterministic heuristics:
1. **Candidate Gathering**: Inspects `ExecutorRegistry` for all registered executors whose `supported_actions` match the step action, or whose strategy aligns with the step's domain.
2. **Deterministic Fallback Ordering**: Candidates are sorted by priority (`API_INTEGRATION` (1) → `APPLICATION_INTEGRATION` (2) → `ACCESSIBILITY_UI` (3) → `BROWSER_AUTOMATION` (4) → `UI_FALLBACK` (5) → `CONTROLLED_LOCAL` (10)).
3. **Capability Filtering**:
   - Matches action and target.
   - Enforces risk boundary: if step risk is higher than executor's maximum supported risk level, the candidate is rejected with an auditable reason.
   - Enforces implementation check: if `capability.implemented is False`, the candidate is rejected with `Strategy '<name>' is architecturally represented but NOT implemented in Phase 10`.
4. **Policy Validation**: The top implemented candidate is validated against `ExecutionPolicyEngine` (checking approval state, parameter resolution, sandbox restrictions, and communication blocks).
5. **Selection Output**:
   - If an implemented, policy-compliant executor is found: returns `StrategySelectionResult(canonical_strategy=..., executor=..., policy_decision=ALLOWED)`.
   - If no implemented executor exists: returns `StrategySelectionResult(canonical_strategy=None, blocked_reason=UNSUPPORTED_EXECUTION_STRATEGY, policy_decision=BLOCKED)`.

### 4. Integration Across the Lifecycle

- **Execution Planning (`ExecutionPlanner`)**: Each `PlannedStep` is evaluated through `StrategySelector` during plan creation. The step's `StepExecutionStrategy` records `canonical_strategy`, `available_strategies_considered`, `rejected_strategies`, `rejection_reasons`, and `executor_implemented`.
- **Dry-Run Simulation (`DryRunSimulator`)**: Dry-run reflects strategy selection without performing real actions. For unsupported steps, dry-run reports `selected_strategy=None` and `policy_decision=BLOCKED`.
- **Live Execution (`ExecutionEngine`)**: The engine resolves the executor via `StrategySelector`. If `selected_strategy` is null or unimplemented, the engine executes fail-closed, returning `ExecutionStepStatus.BLOCKED` with code `UNSUPPORTED_EXECUTION_STRATEGY`.
- **Audit Traceability (`ExecutionAuditRecord`)**: Step audit records capture `selected_strategy`, `selection_reason`, `candidate_strategies`, `fallback_used`, and `blocked_reason`.
- **Verification (`VerificationEngine`)**: Blocked steps yield `NOT_APPLICABLE` verification checks without fabricating false evidence.

---

## Phase 11: Workflow Learning & Reliability Intelligence

### 1. Conceptual Framework: The "LEARN" Stage

Phase 11 completes the observe → identify → understand → specify → approve → plan → select → execute → verify → **LEARN** lifecycle of WorkFlowOS.

Rather than relying on ungrounded AI guesses or continuous auto-mutation, WorkFlowOS treats **historical execution and post-execution verification audits** as empirical ground truth. The system learns:
- Which workflows and steps consistently verify expected state.
- Which steps suffer from state mismatches (verification failures).
- Which steps are blocked due to missing executor capabilities or unresolved parameters.
- What failure patterns occur repeatedly across sessions.

### 2. Strict Human Governance Safeguards

**CRITICAL INVARIANT**: Learning is strictly advisory and read-only.
- **NO Automatic Workflow Modification**: The Learning Engine **NEVER** mutates `CanonicalWorkflowSpec` steps, variables, or boundaries.
- **NO Approval State Tampering**: The engine **NEVER** automatically approves, rejects, or changes human governance metadata.
- **NO Autonomous Execution**: The engine **NEVER** executes workflows or bypasses the human approval requirement.
- **NO External Service Mutations**: Zero network requests or third-party API mutations occur during learning analysis.

### 3. Deterministic Failure Classification

Outcomes are classified without LLM inference using deterministic decision rules:
- **`VERIFICATION_FAILURE`**: The executor reported `SUCCESS`, but post-execution state checks `FAILED` (stronger evidence than executor self-reporting).
- **`EXECUTION_FAILURE`**: The executor threw an exception or returned `FAILED`.
- **`UNSUPPORTED_STRATEGY`**: The step was blocked because no implemented executor supports the action/target.
- **`PARAMETER_PROBLEM`**: The step was blocked because required parameters were unresolved or missing.
- **`POLICY_BLOCK`**: The step was blocked by security policy, sandbox constraints, or unapproved workflow state.
- **`UNKNOWN_OUTCOME`**: Non-actionable or unverified execution status.

### 4. Deterministic Reliability Metrics

All metrics are calculated numerically and deterministically:
- $\text{Total Executions} = \text{Completed} + \text{Failed} + \text{Blocked}$
- $\text{Completed Executable Executions} = \text{Verified} + \text{Failed} + \text{Verification Failures}$
- $\text{Reliability Rate} = \frac{\text{Verified Executions}}{\text{Completed Executable Executions}}$ (measures true verified success)
- $\text{Execution Success Rate} = \frac{\text{Successful Executions}}{\text{Successful Executions} + \text{Failed Executions}}$
- $\text{Verification Rate} = \frac{\text{Verified Executions}}{\text{Successful Executions}}$
- $\text{Blocked Rate} = \frac{\text{Blocked Executions}}{\text{Total Executions}}$

### 5. Empirical Pattern Detection

Deterministic rule-based pattern discovery:
- **`REPEATED_VERIFICATION_FAILURE`**: Triggered when a step accumulates $\ge 2$ verification failures.
- **`REPEATED_UNSUPPORTED_STRATEGY`**: Triggered when a step accumulates $\ge 2$ unsupported strategy blocks.
- **`REPEATED_PARAMETER_PROBLEM`**: Triggered when a step accumulates $\ge 2$ parameter resolution failures.
- **`REPEATED_VERIFIED_SUCCESS`**: Triggered when a workflow accumulates $\ge 2$ verified executions with zero failures.

### 6. Evidence-Backed Improvement Suggestions

Every improvement suggestion is grounded in empirical execution and verification IDs:
- Clearly marked `is_advisory = True` and labeled `SUGGESTION (NOT APPLIED CHANGE)`.
- Recommends concrete actions (e.g. "Review the expected-state definition for Step X", "An implemented execution strategy for Step Y is required").
- Accompanied by exact occurrence counts, affected step IDs, execution IDs, and verification IDs.

### 7. SQLite Persistence & Idempotency

- Persisted in SQLite tables:
  - `workflow_reliability_profiles` (keyed by `workflow_id`)
  - `workflow_learning_events` (chronological audit history)
- `POST /api/workflows/{workflow_id}/learning/refresh` recomputes and persists intelligence idempotently: identical execution history produces identical profiles.

---

## Phase 12 — Real Gmail API Integration (Read-Only Search)

Phase 12 implements the first real external execution integration in WorkFlowOS using Google's official Gmail API.

> [!IMPORTANT]
> **Scope Boundary**: "Phase 12 implements one read-only Gmail API operation."
> WorkFlowOS does NOT fully automate Gmail. Mutating operations (sending, deleting, moving, labeling, marking as read, or downloading attachments) are strictly prohibited.

### 1. Integration Architecture

```
CanonicalWorkflowSpec (Approved)
           ↓
     ExecutionPlan
           ↓
    StrategySelector (API_INTEGRATION & Gmail Target Matching)
           ↓
   ExecutionPolicyEngine (Strict Policy Check)
           ↓
     GmailApiExecutor (strategy: API_INTEGRATION, implemented: True)
           ↓
      GmailApiClient (OAuth 2.0 Client Abstraction)
           ↓
   Google Gmail API (messages.list & messages.get with format='metadata')
           ↓
 Normalized Result (GmailSearchResult & GmailMessageSummary)
           ↓
  VerificationEngine (GmailVerificationStrategy)
           ↓
 ExecutionAuditRecord (Zero Credential Leakage)
           ↓
     LearningEngine (Reliability Profile Update)
```

### 2. OAuth Flow & Authorization Scope

- **Official OAuth 2.0**: Uses Google's official OAuth 2.0 mechanism via `google-auth-oauthlib` and `google-api-python-client`.
- **Minimum Required Scope**: Strictly uses the narrowest read-only scope:
  `https://www.googleapis.com/auth/gmail.readonly`
  Broad read/write scopes (`gmail.modify`, `mail.google.com`, `gmail.compose`) are prohibited.
- **Fail-Closed Security**: If credentials or tokens are unavailable, execution fails closed with `AUTHENTICATION_REQUIRED` or `INTEGRATION_UNAVAILABLE`. Tokens are never logged, committed, or transmitted to the frontend.

### 3. Configuration Architecture

Centralized in `backend/app/config.py`:
- `GMAIL_ENABLED`: Boolean flag toggling Gmail integration (default `False`).
- `GMAIL_CREDENTIALS_PATH`: Path to OAuth client `credentials.json` (defaults to project root).
- `GMAIL_TOKEN_PATH`: Path to authorized user `token.json` (defaults to project root).
- `GMAIL_SCOPES`: Frozen list `["https://www.googleapis.com/auth/gmail.readonly"]`.

### 4. Supported Gmail Operation

- **Action Name**: `search_email`
- **Target Application**: `Gmail`
- **Execution Strategy**: `API_INTEGRATION`
- **Behavior**: Deterministically queries the Gmail API using an approved parameter query (e.g. `from:supplier@example.com subject:invoice`), retrieves matching message metadata, normalizes records into structured summaries, and outputs total count and sample message headers.
- **Prohibited Operations**: Deletion, sending, draft creation, label modification, moving to trash, marking as read, and arbitrary attachment downloads are strictly prohibited.

### 5. Response Normalization & Privacy Safeguards

The executor does not expose raw API dictionaries. It normalizes outputs into minimal Pydantic models (`backend/app/models/gmail.py`):
- `message_id`, `thread_id`
- `sender`, `subject`, `timestamp`, `snippet`
Zero full email bodies are stored. Zero access or refresh tokens are persisted in memory or logs.

### 6. Post-Execution Verification

`GmailVerificationStrategy` evaluates executed steps deterministically:
- Verifies that `search_email` was called with the approved query parameter.
- Evaluates structured output presence (`query`, `total_found`, normalized message summaries).
- Evidence stores non-sensitive metadata (query string, result count, and message IDs only).
- Produces `VERIFIED` status upon success, or `FAILED` if output is missing or corrupted.

### 7. Audit & Learning Integration

- **Execution Audit**: Every run records an `ExecutionAuditRecord` capturing strategy (`API_INTEGRATION`), executor (`GmailApiExecutor`), operation (`search_email`), and execution duration without token leakage.
- **Phase 11 Learning**: The `LearningEngine` aggregates Gmail execution and verification outcomes into the workflow reliability profile (`total_executions`, `verified_executions`, `execution_success_rate`, `verification_rate`).

### 8. Security Boundaries

- Zero token leakage in logs, audit records, or frontend responses.
- No fallback to `ControlledLocalExecutor` if Gmail is unavailable.
- Deterministic query parameters bound from approved workflow specifications only; no runtime LLM-generated API queries.

---

## What is NOT Implemented Yet (Phase 13+)

- **NO Gmail Mutation Operations**: No email sending, deleting, archiving, moving, labeling, or draft composition.
- **NO CRM or Slack Integration**: Salesforce, HubSpot, and Slack integrations remain represented but unimplemented stubs.
- **NO Browser Automation Engine**: No Playwright, Selenium, or Puppeteer automation.
- **NO Desktop Input Automation**: No PyAutoGUI, mouse clicks, keyboard typing, or window hijacking.
- **NO Autonomous Workflow Auto-Editing**: Workflow improvements require explicit human review and approval.





