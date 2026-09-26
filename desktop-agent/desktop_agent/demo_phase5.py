"""Demonstration script: Semantic Understanding & Intent Translation (Phase 5).

Demonstrates:
1. Loading multi-session activity data.
2. Ingesting into WorkFlowOS backend and extracting deterministic WorkflowDNA.
3. Triggering AI Semantic Interpretation via POST /api/workflows/{dna_id}/interpret.
4. Comparing:
   - DETERMINISTIC GROUND TRUTH (WorkflowDNA)
   - AI INTERPRETATION (Validated SemanticWorkflow)
5. Demonstrating that the LLM receives structured WorkflowDNA (not raw desktop events)
   and produces NO executable automation code.
"""

import json
import os
from pathlib import Path
import sys
import urllib.request

# Ensure repo root and backend are on sys.path for direct execution
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _dir in [str(_REPO_ROOT), str(_REPO_ROOT / "backend"), str(_REPO_ROOT / "desktop-agent")]:
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

from app.config import GEMINI_API_KEY
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset

# Ensure terminal stdout safely prints UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_phase5_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    print("==================================================================")
    print("      WorkFlowOS Phase 5: Semantic Understanding & Intent         ")
    print("==================================================================")
    print(f"Backend Target URL : {backend_url}")
    print("Architecture       : Raw Events -> Segment -> Discover -> DNA -> Semantic Engine -> LLM")
    print("LLM Role           : Semantic Interpretation ONLY (NO executable automation code)")
    print("==================================================================\n")

    # 1. Ingest test dataset
    events = generate_deterministic_dataset()
    print(f"1. Ingesting {len(events)} structured ActivityEvents into backend /api/events...")
    for evt in events:
        req = urllib.request.Request(
            f"{backend_url}/api/events",
            data=json.dumps(evt.model_dump(mode="json")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                pass
        except Exception as err:
            print(f"Error connecting to backend at {backend_url}: {err}")
            print("Please ensure the backend is running: python -m uvicorn app.main:app --app-dir backend")
            return

    print("   Events successfully ingested.")

    # 2. Query Workflow DNA
    print("\n2. Fetching deterministic WorkflowDNA via GET /api/workflows/dna...")
    dna_url = f"{backend_url}/api/workflows/dna?inactivity_timeout=120.0&min_occurrences=2&similarity_threshold=0.65"
    with urllib.request.urlopen(dna_url) as resp:
        dna_list_resp = json.loads(resp.read().decode("utf-8"))

    if dna_list_resp["dna_count"] == 0:
        print("No Workflow DNA found. Exiting.")
        return

    top_dna = dna_list_resp["dna_items"][0]
    dna_id = top_dna["dna_id"]
    print(f"   Found Workflow DNA: {dna_id}")
    print(f"   Signature: {top_dna['normalized_signature']}")

    # 3. Trigger Semantic Interpretation
    print(f"\n3. Requesting Semantic Interpretation via POST /api/workflows/{dna_id}/interpret...")
    provider_override = "gemini" if (GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")) else "mock"
    print(f"   Using Provider: {provider_override.upper()} ({'Live Gemini API' if provider_override == 'gemini' else 'Deterministic Mock Provider'})")

    interpret_url = f"{backend_url}/api/workflows/{dna_id}/interpret?provider_type={provider_override}&similarity_threshold=0.65"
    post_req = urllib.request.Request(interpret_url, data=b"", headers={}, method="POST")

    with urllib.request.urlopen(post_req) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    print(f"   Status            : {result['status'].upper()}")
    print(f"   Validation Passed : {result['validation_passed']}")
    print(f"   Message           : {result['message']}\n")

    if not result["semantic_workflow"]:
        print("Semantic workflow interpretation not available (fallback mode).")
        return

    sem_wf = result["semantic_workflow"]

    # 4. Display Side-by-Side Comparison
    print("==================================================================")
    print("          DETERMINISTIC GROUND TRUTH vs AI INTERPRETATION         ")
    print("==================================================================")

    print("\n[PART 1: OBSERVED / DETERMINISTIC FACTS (WorkflowDNA)]")
    print(f"  * DNA ID             : {top_dna['dna_id']}")
    print("  * Core Steps (100%)  : " + " -> ".join([s["application"] for s in top_dna["invariant_steps"]]))
    print("  * Structural Params  : " + ", ".join([v["parameter_name"] for v in top_dna["variable_parameters"]]))
    for var in top_dna["variable_parameters"]:
        print(f"    - {var['parameter_name']}: observed values {var['observed_values']}")
    print(f"  * Evidence Quote     : \"{top_dna['evidence']['invariant_evidence']}\"")

    print("\n[PART 2: AI SEMANTIC INTERPRETATION (Validated by Engine)]")
    print(f"  * Semantic Title     : {sem_wf['title']}")
    print(f"  * Operational Intent : {sem_wf['intent']}")
    print(f"  * Executive Summary  : {sem_wf['summary']}\n")

    print("  * Semantic Variable Mappings:")
    for sv in sem_wf["semantic_variables"]:
        conf_pct = int(sv["model_interpretation_confidence"] * 100)
        print(f"    - {sv['semantic_name']} <- {sv['source_parameter']}")
        print(f"      Reason     : {sv['reason']}")
        print(f"      Confidence : {conf_pct}% (Explicit LLM Estimate)")

    print("\n  * Semantic Step Intent Breakdown:")
    for idx, st in enumerate(sem_wf["semantic_steps"], 1):
        print(f"    {idx}. [{st['application']}] {st['action']}")
        print(f"       Intent   : {st['description']}")
        print(f"       DNA Key  : {st['source_dna_step_key']}")
        print(f"       Citation : {st['evidence_reference']}")

    if sem_wf["optional_steps"]:
        print("\n  * Optional Branches:")
        for opt in sem_wf["optional_steps"]:
            print(f"    - [{opt['application']}] Condition: {opt['condition_or_trigger']}")
            print(f"      Description: {opt['description']}")

    print(f"\n  * Interpretation Notes: {sem_wf['interpretation_notes']}")
    print(f"  * Model Provider       : {sem_wf['model_provider']}")
    print("==================================================================")
    print("Notice: The LLM acted solely as a semantic interpreter.")
    print("No browser automation, click coordinates, or execution scripts were created.")
    print("==================================================================\n")


if __name__ == "__main__":
    run_phase5_demo()
