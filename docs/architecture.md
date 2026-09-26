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
Phase 6+ answers:  "How do we safely execute it?"
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

## What is NOT Implemented Yet (Phase 6+)

- **NO Workflow Code Generation**: The LLM outputs structured semantic models (`SemanticWorkflow`), not Python/JavaScript code.
- **NO Browser / Desktop Automation**: No Playwright, Selenium, or mouse/keyboard injection.
- **NO Third-Party API Execution**: No active mutation of Gmail, CRM, or Slack.
- **NO User Approval / Automation Trigger**: UI is strictly an analytical and intent inspection view.


