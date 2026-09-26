"""Demonstration script: Workflow DNA Extractor (Phase 4).

Demonstrates:
1. Loading multi-session activity data containing:
   - 3 repeated Customer Replacement Request workflows:
     * Variable window titles: Rahul, Ananya, Vikram
     * Variable filenames: invoice_101.pdf, invoice_102.pdf, invoice_103.pdf
     * 1 instance with an optional step: Microsoft Excel
   - 1 distinct Developer workflow (isolated)
   - 1 noise session (Spotify + Calculator)
2. Ingesting into WorkFlowOS backend.
3. Querying GET /api/workflows/dna.
4. Printing the extracted Workflow DNA:
   - Core / Invariant Steps
   - Variable Parameters & Templates
   - Optional Steps
   - Ordering Precedence
   - Structural Preconditions & Boundaries
   - Explainable Evidence
"""

import json
import os
import sys
import urllib.request
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset

# Ensure terminal stdout safely prints UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_phase4_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    print("==================================================================")
    print("           WorkFlowOS Phase 4: Workflow DNA Extraction            ")
    print("==================================================================")
    print(f"Backend Target URL : {backend_url}")
    print("Core Capabilities  : Invariants, Variables, Optionals, Ordering, Preconditions")
    print("AI / LLM Calls     : NONE (100% Deterministic & Explainable)")
    print("==================================================================\n")

    # 1. Generate test dataset
    events = generate_deterministic_dataset()
    print(f"1. Generated {len(events)} structured ActivityEvents across 5 distinct activity sessions.")

    # 2. Ingest events into the backend
    print("2. Ingesting events into backend /api/events...")
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

    print(f"   Successfully stored {len(events)} events in SQLite database.")

    # 3. Trigger Workflow DNA Analysis
    print("\n3. Triggering Workflow DNA Extraction via GET /api/workflows/dna...")
    dna_url = f"{backend_url}/api/workflows/dna?inactivity_timeout=120.0&min_occurrences=2&similarity_threshold=0.65"
    with urllib.request.urlopen(dna_url) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    print(f"   Total Candidates Analyzed : {result['total_candidates_analyzed']}")
    print(f"   Workflow DNA Generated    : {result['dna_count']}\n")

    # 4. Display Workflow DNA Items
    for idx, dna in enumerate(result["dna_items"], 1):
        print("==================================================================")
        print(f"                       WORKFLOW DNA #{idx}                        ")
        print("==================================================================")
        print(f"  DNA ID              : {dna['dna_id']}")
        print(f"  Source Candidate ID : {dna['source_candidate_id']}")
        print(f"  Normalized Signature: {dna['normalized_signature']}\n")

        print("  1. CORE / INVARIANT STEPS:")
        for inv in dna["invariant_steps"]:
            ratio_pct = int(inv["occurrence_ratio"] * 100)
            print(f"     [+] [{inv['application']}] {inv['event_type']} ({inv['occurrences']}/{inv['total_sessions']} sessions, {ratio_pct}%)")

        print("\n  2. VARIABLE PARAMETERS:")
        if not dna["variable_parameters"]:
            print("     (No variable parameters detected)")
        for var in dna["variable_parameters"]:
            pattern_str = f" [Pattern: {var['pattern_template']}]" if var["pattern_template"] else ""
            print(f"     * {var['parameter_name']} (from {var['source_field']}){pattern_str}")
            print(f"       Associated Step : {var['associated_step_key']} in {var['associated_application']}")
            print(f"       Observed Values : {var['observed_values']}")
            print(f"       Distinct Count  : {var['distinct_value_count']} across {var['total_observations']} observations (variation: {var['variation_ratio']})")

        print("\n  3. OPTIONAL STEPS:")
        if not dna["optional_steps"]:
            print("     (No optional steps; all executions adhered to core steps)")
        for opt in dna["optional_steps"]:
            ratio_pct = int(opt["occurrence_ratio"] * 100)
            print(f"     ? [{opt['application']}] {opt['event_type']} ({opt['occurrences']}/{opt['total_sessions']} sessions, {ratio_pct}%)")

        print("\n  4. ORDERING CONSTRAINTS:")
        for oc in dna["ordering_constraints"]:
            print(f"     -> {oc['description']} (Consistency: {int(oc['consistency_ratio'] * 100)}%)")

        print("\n  5. PRECONDITIONS & BOUNDARIES:")
        for prec in dna["preconditions"]:
            print(f"     * {prec}")
        b = dna["boundaries"]
        print(f"     Boundary Range   : First '{b['first_step']}' -> Last '{b['last_step']}'")
        print(f"     Duration Stats   : Min {b['min_duration_seconds']}s | Avg {b['average_duration_seconds']}s | Max {b['max_duration_seconds']}s")

        print("\n  6. EXPLAINABLE EVIDENCE:")
        ev = dna["evidence"]
        print(f"     Supporting Count : {ev['supporting_session_count']} sessions")
        print(f"     Invariants       : {ev['invariant_evidence']}")
        print(f"     Variables        : {ev['variable_evidence']}")
        print(f"     Optionals        : {ev['optional_step_evidence']}")
        print(f"     Ordering         : {ev['ordering_evidence']}")
        print(f"     Boundaries       : {ev['boundary_evidence']}")
        print("==================================================================\n")

    print("Phase 4 Verification complete. Next phase (Phase 5) will interpret structural variables into semantic intent using AI.")


if __name__ == "__main__":
    run_phase4_demo()
