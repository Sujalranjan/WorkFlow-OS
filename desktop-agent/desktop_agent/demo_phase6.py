"""Demonstration script: Canonical Workflow Specification, Risk Analysis & User Approval (Phase 6).

Demonstrates:
1. Ingesting multi-session activity events and extracting deterministic WorkflowDNA.
2. Generating validated SemanticWorkflow interpretation via Gemini/Mock provider.
3. Assembling the formal CanonicalWorkflowSpec combining DNA constraints with semantic intent.
4. Deterministic Parameter Binding & Type Inference (string, filename, identifier).
5. User customization of semantic parameter names while keeping DNA source parameters immutable.
6. Explainable step-by-step Risk Analysis (read_only, local_change, external_change, communication).
7. Human Governance Approval lifecycle: 'requires_review' -> 'approved'.
8. Safety Termination: Proving that approval accepts the workflow contract and STOPS without execution.
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


def run_phase6_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    print("==================================================================")
    print("      WorkFlowOS Phase 6: Canonical Specification & Governance    ")
    print("==================================================================")
    print(f"Backend Target URL : {backend_url}")
    print("Architecture       : DNA + Semantic -> Canonical Spec -> Parameter Binding -> Risk -> Human Approval")
    print("Safety Principle   : Approval confirms specification intent ONLY (STRICTLY NO EXECUTION)")
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

    if not result.get("semantic_workflow"):
        print(f"Semantic interpretation failed: {result.get('message')}")
        return

    semantic_wf = result["semantic_workflow"]
    sem_id = semantic_wf["semantic_workflow_id"]
    print(f"   Semantic Workflow ID: {sem_id}")
    print(f"   Title               : {semantic_wf['title']}")

    # 4. Generate Formal Canonical Workflow Specification
    print(f"\n4. Generating Canonical Workflow Specification via POST /api/workflows/{sem_id}/specification...")
    spec_url = f"{backend_url}/api/workflows/{sem_id}/specification"
    spec_req = urllib.request.Request(spec_url, data=b"", headers={}, method="POST")

    with urllib.request.urlopen(spec_req) as resp:
        spec = json.loads(resp.read().decode("utf-8"))

    workflow_id = spec["workflow_id"]
    print(f"   Canonical Workflow ID: {workflow_id}")
    print(f"   Initial State        : {spec['approval_state']['state'].upper()} (Human Review Required)")
    print(f"   Overall Risk Level   : {spec['risk_assessment']['overall_risk_level'].upper()}")

    # 5. Display Parameter Bindings
    print("\n==================================================================")
    print("                     PARAMETER BINDINGS & TYPES                   ")
    print("==================================================================")
    print("Notice: Each structural DNA parameter remains independently traceable.")
    for idx, b in enumerate(spec["variables"], 1):
        print(f"  {idx}. Semantic Name : {b['semantic_name']}")
        print(f"     Source DNA Param: {b['source_parameter']} (IMMUTABLE)")
        print(f"     Source Field    : {b['source_field']}")
        print(f"     Inferred Type   : {b['inferred_type'].upper()} (Deterministic, NO LLM)")
        print(f"     Observed Values : {b['observed_values']}")

    # 6. Customize a Parameter Binding via PATCH
    first_param = spec["variables"][0]["source_parameter"]
    new_name = "client_account_name"
    print(f"\n5. Customizing Parameter '{first_param}' -> '{new_name}' via PATCH...")
    patch_payload = {
        "updates": [
            {
                "source_parameter": first_param,
                "semantic_name": new_name,
            }
        ]
    }
    patch_req = urllib.request.Request(
        f"{backend_url}/api/workflows/specifications/{workflow_id}/parameters",
        data=json.dumps(patch_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(patch_req) as resp:
        spec = json.loads(resp.read().decode("utf-8"))

    modified_var = next(v for v in spec["variables"] if v["source_parameter"] == first_param)
    print(f"   Updated Semantic Name: {modified_var['semantic_name']}")
    print(f"   Source Parameter     : {modified_var['source_parameter']} (Unchanged)")
    print(f"   Binding Status       : {modified_var['binding_status'].upper()}")

    # 7. Display Step-by-Step Traceability and Risk Analysis
    print("\n==================================================================")
    print("            CANONICAL STEPS, TRACEABILITY & RISK ANALYSIS         ")
    print("==================================================================")
    for idx, st in enumerate(spec["steps"], 1):
        r = st["risk"]
        print(f"  Step {idx}: [{st['application']}] {st['action']}")
        print(f"    * Traceability Chain : Canonical '{st['canonical_step_id']}' -> Semantic '{st['source_semantic_step_id']}' -> DNA '{st['source_dna_step_key']}'")
        print(f"    * Evidence Reference : {st['evidence_reference']}")
        print(f"    * Risk Category      : {r['risk_category'].upper()} | Severity: {r['risk_level'].upper()}")
        print(f"    * Classification Why : {r['reason']}")
        print(f"    * Needs Confirmation : {r['requires_confirmation']}")
        print()

    print(f"  * Risk Assessment Summary: {spec['risk_assessment']['summary']}")

    # 8. Human Approval Action
    print("\n==================================================================")
    print("                      HUMAN APPROVAL GOVERNANCE                   ")
    print("==================================================================")
    print("Simulating human reviewer accepting the canonical specification...")
    approve_payload = {
        "reviewer": "sarah.lead@company.com",
        "comments": "Audited step sequence, risk levels, and parameter bindings. Specification approved for catalog.",
    }
    approve_req = urllib.request.Request(
        f"{backend_url}/api/workflows/specifications/{workflow_id}/approve",
        data=json.dumps(approve_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(approve_req) as resp:
        spec = json.loads(resp.read().decode("utf-8"))

    appr = spec["approval_state"]
    print(f"   Final Approval State : {appr['state'].upper()}")
    print(f"   Approved By          : {appr['reviewed_by']}")
    print(f"   Approved At          : {appr['reviewed_at']}")
    print(f"   Reviewer Comments    : {appr['comments']}")

    print("\n==================================================================")
    print("                     SAFETY GUARANTEE CONFIRMATION                ")
    print("==================================================================")
    print("CRITICAL PRINCIPLE: Approval means the human accepts the specification.")
    print("NO automated task, browser action, or external mutation was executed.")
    print("Phase 6 establishes the verified workflow contract. Execution belongs to future phases.")
    print("==================================================================\n")


if __name__ == "__main__":
    run_phase6_demo()
