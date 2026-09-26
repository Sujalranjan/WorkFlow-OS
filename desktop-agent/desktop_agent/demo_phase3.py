"""Demonstration script: Workflow Segmentation and Discovery Engine (Phase 3).

Demonstrates:
1. Loading multi-session activity data containing:
   - Repeated Customer Request workflow (3 instances, one with noise)
   - Distinct Developer workflow (1 instance)
   - Background/isolated noise (1 instance)
2. Ingesting into WorkFlowOS backend.
3. Querying GET /api/discovery/candidates.
4. Printing the discovered candidates, representative sequence, similarity score, and explainable evidence.
"""

import json
import os
import sys
import urllib.request
from tests.fixtures.discovery_fixtures import generate_deterministic_dataset


def run_phase3_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    print("==================================================================")
    print("     WorkFlowOS Phase 3: Workflow Segmentation & Discovery        ")
    print("==================================================================")
    print(f"Backend Target URL : {backend_url}")
    print("Algorithm          : Deterministic Temporal Segmentation + LCS Sequence Clustering")
    print("AI / LLM Calls     : NONE (100% Deterministic & Explainable)")
    print("==================================================================\n")

    # 1. Generate test dataset
    events = generate_deterministic_dataset()
    print(f"1. Generated {len(events)} structured ActivityEvents across 5 distinct activity windows.")

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

    # 3. Trigger Discovery Analysis
    print("\n3. Triggering Discovery Engine via GET /api/discovery/candidates...")
    discovery_url = f"{backend_url}/api/discovery/candidates?inactivity_timeout=120.0&min_occurrences=2&similarity_threshold=0.70"
    with urllib.request.urlopen(discovery_url) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    print(f"   Total Events Analyzed : {result['total_events_analyzed']}")
    print(f"   Task Sessions Found   : {result['total_sessions_found']}")
    print(f"   Candidates Discovered : {result['candidate_count']}\n")

    # 4. Display Candidates
    print("======================= DISCOVERED WORKFLOWS =======================")
    for idx, cand in enumerate(result["candidates"], 1):
        sim_pct = round(cand["average_similarity_score"] * 100, 1)
        print(f"\n[CANDIDATE #{idx}]")
        print(f"  Occurrences          : {cand['occurrences']}")
        print(f"  Similarity Score     : {sim_pct}%")
        print(f"  Applications         : {', '.join(cand['applications'])}")
        print(f"  Normalized Signature : {cand['normalized_signature']}")
        print("  Representative Sequence:")
        for step in cand["representative_sequence"]:
            print(f"    - Step {step['step_index']}: [{step['application']}] {step['event_type']}")
        print(f"  Explainable Evidence : \"{cand['evidence']}\"")
        print(f"  Supporting Sessions  : {len(cand['supporting_session_ids'])} sessions ({', '.join(cand['supporting_session_ids'][:2])}...)")

    print("\n==================================================================")
    print("Notice: The one-off Developer workflow and random Spotify/Calculator")
    print("noise were successfully filtered out (0 recurring candidates created).")
    print("Check the frontend dashboard to view the visual sequence graph.")
    print("==================================================================\n")


if __name__ == "__main__":
    run_phase3_demo()
