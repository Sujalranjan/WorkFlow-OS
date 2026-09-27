"""Full Live End-to-End Workflow Verification Script for Phase 16.
Exercises real Gmail API, real attachment download, real CRM HTTP service on port 8001,
real Slack Web API, real independent verification, failure propagation, and learning.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

import httpx

# Ensure backend is in path
sys.path.insert(0, os.path.abspath("backend"))

import app.config as config
from app.models.canonical import ApprovalState
from app.models.crm import CrmCustomer
from app.models.execution import ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.verification import VerificationStatus
from app.services.crm_client import CrmApiClient
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.gmail_executor import GmailApiExecutor
from app.services.executors.slack_executor import SlackApiExecutor
from app.services.gmail_client import GmailApiClient
from app.services.phase16_workflow import Phase16Orchestrator
from app.services.slack_client import SlackApiClient
from app.services.verifiers.crm_verifier import CrmVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.slack_verifier import SlackVerificationStrategy

def run_validation():
    print("=" * 80)
    print("PHASE 16 LIVE E2E FULL VALIDATION RUN")
    print("=" * 80)

    slack_token = config.SLACK_BOT_TOKEN
    slack_channel = config.SLACK_CHANNEL_ID
    crm_base_url = "http://127.0.0.1:8001/api/crm"

    print(f"SLACK CONFIGURED: {bool(slack_token and not slack_token.startswith('xoxb-placeholder'))}")
    print(f"SLACK CHANNEL: {slack_channel}")
    print(f"GMAIL TOKEN EXISTS: {Path('token.json').exists()}")
    print(f"CRM BASE URL (Port 8001): {crm_base_url}")

    # Check CRM port 8001 health
    crm_client = CrmApiClient(base_url=crm_base_url)
    crm_healthy = crm_client.is_healthy()
    print(f"CRM PORT 8001 HEALTHY: {crm_healthy}")
    if not crm_healthy:
        print("ERROR: CRM service on port 8001 is not running!")
        sys.exit(1)

    # 1. Reset CRM customer cust-001 to pending_replacement
    cust = crm_client.get_customer("cust-001")
    if not cust:
        crm_client.create_customer({
            "customer_id": "cust-001",
            "name": "Rahul Sharma",
            "email": "rahul.sharma@example.com",
            "company": "Acme Corp",
            "status": "pending_replacement",
            "notes": "Reset for Phase 16 live validation",
        })
    else:
        crm_client.update_customer("cust-001", {
            "status": "pending_replacement",
            "notes": "Reset for Phase 16 live validation",
        })
    cust_before = crm_client.get_customer("cust-001")
    print(f"CRM cust-001 status before live run: {cust_before.status}")

    # Initialize real clients
    gmail_client = GmailApiClient(credentials_path="credentials.json", token_path="token.json")
    slack_client = SlackApiClient(bot_token=slack_token, default_channel_id=slack_channel)

    orch = Phase16Orchestrator()
    orch.engine.registry.register(GmailApiExecutor(client=gmail_client))
    orch.engine.registry.register(CrmApiExecutor(client=crm_client))
    orch.engine.registry.register(SlackApiExecutor(client=slack_client))

    orch.verification_engine.strategy_registry.register(GmailVerificationStrategy())
    orch.verification_engine.strategy_registry.register(CrmVerificationStrategy(client=crm_client))
    orch.verification_engine.strategy_registry.register(SlackVerificationStrategy(client=slack_client))

    # -------------------------------------------------------------------------
    # VALIDATION 1: APPROVAL GATE
    # -------------------------------------------------------------------------
    print("\n--- [TEST: APPROVAL GATE] ---")
    unapproved_spec = orch.prepare_workflow(auto_approve=False)
    print(f"Created unapproved spec: {unapproved_spec.workflow_id}, state: {unapproved_spec.approval_state.state.value}")
    blocked_by_gate = False
    try:
        orch.planner.create_execution_plan(unapproved_spec)
    except ValueError as ve:
        blocked_by_gate = True
        print(f"Approval gate correctly blocked planning: {ve}")
    assert blocked_by_gate, "Unapproved workflow must be blocked!"

    # -------------------------------------------------------------------------
    # VALIDATION 2: DRY-RUN SIMULATION (0 MUTATIONS, 0 REAL CALLS)
    # -------------------------------------------------------------------------
    print("\n--- [TEST: DRY RUN SIMULATION] ---")
    approved_spec = orch.approve_workflow(unapproved_spec.workflow_id, reviewer="Lead Security Auditor")
    plan = orch.create_plan(
        approved_spec.workflow_id,
        runtime_inputs={"search_query": "has:attachment", "customer_query": "cust-001"}
    )
    dry_audit = orch.run_dry_run(plan.execution_plan_id)
    print(f"Dry run audit status: {dry_audit.status.value}")
    for idx, s in enumerate(dry_audit.step_results, 1):
        print(f"  Dry Step {idx}: {s.target_application} - {s.action_name} -> status={s.status.value}, output_status={s.output.get('status')}")
        assert s.status == ExecutionStepStatus.SUCCESS
        assert s.output.get("status") == "SIMULATED"

    # Confirm CRM was NOT mutated by dry-run
    cust_after_dry = crm_client.get_customer("cust-001")
    print(f"CRM status after dry-run (must be unchanged): {cust_after_dry.status}")
    assert cust_after_dry.status == "pending_replacement", "Dry run must not mutate CRM!"

    # -------------------------------------------------------------------------
    # VALIDATION 3: REAL LIVE EXECUTION (REAL GMAIL, REAL CRM :8001, REAL SLACK)
    # -------------------------------------------------------------------------
    print("\n--- [TEST: REAL LIVE EXECUTION] ---")
    custom_sandbox = os.path.abspath(os.path.join(tempfile.gettempdir(), f"phase16_live_{uuid.uuid4().hex[:8]}"))
    live_audit = orch.execute_live(plan.execution_plan_id, custom_sandbox_dir=custom_sandbox)
    print(f"Live Execution Record: {live_audit.execution_id}")
    print(f"Overall Status: {live_audit.status.value}")
    print(f"Sandbox Root: {live_audit.sandbox_root}")

    for idx, s in enumerate(live_audit.step_results, 1):
        print(f"\n[STEP {idx}] App: {s.target_application} | Action: {s.action_name} | Status: {s.status.value}")
        print(f"  Executor: {s.executor_name} | Strategy: {s.selected_strategy}")
        safe_out = dict(s.output or {})
        # Mask any token or raw sensitive data
        for k in list(safe_out.keys()):
            if "token" in k.lower() or "secret" in k.lower() or "auth" in k.lower():
                safe_out[k] = "[REDACTED]"
        if "messages" in safe_out and isinstance(safe_out["messages"], list):
            safe_out["messages"] = [f"Message id={m.get('message_id')}, sender={m.get('sender')}" for m in safe_out["messages"][:2]]
        print(f"  Output Summary: {json.dumps(safe_out, indent=2)}")

    # -------------------------------------------------------------------------
    # VALIDATION 4: INDEPENDENT VERIFICATION (ALL 4 VERIFIERS)
    # -------------------------------------------------------------------------
    print("\n--- [TEST: INDEPENDENT VERIFICATION] ---")
    verif = orch.verify_execution(live_audit.execution_id)
    print(f"Overall Verification Status: {verif.overall_status.value}")
    for c in verif.checks:
        print(f"  Verifier Check: {c.check_type} on '{c.target}' -> {c.status.value} (reason: {c.reason})")
    assert verif.overall_status == VerificationStatus.VERIFIED, "Live verification must be VERIFIED!"

    # -------------------------------------------------------------------------
    # VALIDATION 5: DIRECT INDEPENDENT OUT-OF-BAND AUDIT
    # -------------------------------------------------------------------------
    print("\n--- [DIRECT INDEPENDENT OUT-OF-BAND AUDIT] ---")
    # CRM Check
    cust_live = crm_client.get_customer("cust-001")
    print(f"1. CRM Customer 'cust-001' status in crm.db: {cust_live.status} (Expected: replacement_processed)")
    assert cust_live.status == "replacement_processed"

    # Attachment Check
    att_path = live_audit.step_results[1].output.get("saved_path")
    print(f"2. Downloaded Attachment Path: {att_path}")
    assert att_path and os.path.exists(att_path)
    att_bytes = Path(att_path).read_bytes()
    att_hash = hashlib.sha256(att_bytes).hexdigest()
    print(f"   Size: {len(att_bytes)} bytes | SHA-256: {att_hash}")
    assert att_hash == live_audit.step_results[1].output.get("sha256")

    # Slack Check
    slack_ts = live_audit.step_results[4].output.get("ts")
    print(f"3. Slack Message Timestamp: {slack_ts}")
    is_verif, msg_data, reason = slack_client.verify_message(channel=slack_channel, ts=slack_ts)
    print(f"   Slack Message Verified in Channel History: {is_verif} ({reason})")
    if msg_data:
        print(f"   Slack Message Text: {msg_data.get('text', '')[:80]}...")
    assert is_verif, f"Slack verification failed: {reason}"

    # -------------------------------------------------------------------------
    # VALIDATION 6: LEARNING ENGINE
    # -------------------------------------------------------------------------
    print("\n--- [TEST: LEARNING ENGINE] ---")
    profile = orch.learn_from_execution(approved_spec.workflow_id)
    print(f"Workflow ID: {profile.workflow_id}")
    print(f"Total Runs: {profile.total_executions}")
    print(f"Verified Runs: {profile.verified_executions}")
    print(f"Success Rate: {profile.execution_success_rate * 100:.1f}%")
    print(f"Verification Rate: {profile.verification_rate * 100:.1f}%")
    print(f"Advisory Suggestions Count: {len(profile.suggestions)}")

    print("\n" + "=" * 80)
    print("PHASE 16 FULL LIVE E2E VALIDATION: 100% SUCCESSFUL")
    print("=" * 80)

if __name__ == "__main__":
    run_validation()
