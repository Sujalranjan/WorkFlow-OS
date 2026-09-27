"""Real HTTP Execution & Verification Tests for WorkFlowOS CRM (Phase 15C).

Validates the complete real HTTP pipeline without mocks or TestClient fallbacks:
    WorkFlowOS Engine
         |
         | HTTP REST
         v
    Demo CRM Service (Port 8001)
         |
         v
    crm.db (Independent SQLite DB)

Verifies:
1. Real HTTP server lifecycle on localhost:8001.
2. CrmApiClient in live mode strictly requires real HTTP and NEVER silently falls back to TestClient.
3. Full end-to-end plan execution with real HTTP calls (lookup -> update -> query persistence).
4. Independent verification using out-of-band HTTP GET with SHA-256 evidence.
5. Idempotent execution of repeated identical updates.
6. Zero HTTP requests and zero DB writes during dry-run.
7. Policy boundary enforcement: Unapproved CRM updates remain BLOCKED.
8. Safe failure handling for offline servers, missing customers, and state mismatches.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Generator
import uuid

import httpx
import pytest
import uvicorn

from app.crm_server import crm_app
from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.crm import CrmCustomer, CrmSearchResult
from app.models.dna import DNAEvidence, WorkflowBoundaries
from app.models.execution import (
    ExecutionContext,
    ExecutionMode,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    PlannedStep,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.models.strategy import ExecutionStrategyType
from app.models.verification import VerificationStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.crm_repository import CrmRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.services.crm_client import (
    CrmApiClient,
    CrmApiError,
    CrmConnectionError,
    CrmCustomerNotFoundError,
)
from app.services.execution_engine import ExecutionEngine
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.crm_verifier import CrmVerificationStrategy


@pytest.fixture(scope="module")
def live_crm_service() -> Generator[str, None, None]:
    """Launches the real independent CRM server on port 8001 in a daemon thread."""
    port = 8001
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}/api/crm"

    config = uvicorn.Config(crm_app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll health endpoint until responsive
    healthy = False
    deadline = time.time() + 6.0
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            time.sleep(0.15)

    if not healthy:
        server.should_exit = True
        pytest.fail("Failed to start independent CRM server on port 8001.")

    yield base_url

    # Clean shutdown
    server.should_exit = True
    thread.join(timeout=3.0)


# =========================================================================
# 1. Independent Server Lifecycle & Real HTTP No-Fallback Guarantee
# =========================================================================
def test_real_crm_server_independent_lifecycle(live_crm_service):
    """Confirm the independent CRM server is running and accessible over real HTTP."""
    resp = httpx.get(f"{live_crm_service}/health", timeout=3.0)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "WorkFlowOS Demo CRM API"


def test_crm_client_live_mode_never_falls_back_when_server_unavailable():
    """In live mode, CrmApiClient MUST raise CrmConnectionError when the server is down.

    It must NOT silently fall back to TestClient or execute in-process.
    """
    offline_url = "http://127.0.0.1:59999/api/crm"
    client = CrmApiClient(base_url=offline_url, timeout=1.0)

    # Health check returns False
    assert client.is_healthy() is False

    # Find customer must raise CrmConnectionError
    with pytest.raises(CrmConnectionError) as exc_find:
        client.find_customer(query="Acme")
    assert "CRM API unavailable" in str(exc_find.value) or "connection failed" in str(exc_find.value)

    # Update customer must raise CrmConnectionError
    with pytest.raises(CrmConnectionError) as exc_upd:
        client.update_customer("cust-acme-001", {"status": "TEST"})
    assert "CRM API unavailable" in str(exc_upd.value) or "connection failed" in str(exc_upd.value)


# =========================================================================
# 2. End-to-End Real HTTP Execution (Find -> Update -> Verify)
# =========================================================================
def test_real_http_e2e_crm_execution_and_verification(live_crm_service):
    """Full real HTTP execution and independent verification against live CRM server.

    Steps:
    1. Reset CRM to known baseline.
    2. Inspect initial customer state (Before: status='PENDING_INVOICE').
    3. Execute find_customer via CrmApiExecutor over real HTTP.
    4. Execute update_customer_record via CrmApiExecutor over real HTTP.
    5. Query live CRM service via direct HTTP to confirm database mutation persisted.
    6. Execute CrmVerificationStrategy to perform independent verification.
    """
    # 1. Real HTTP client connected to live service
    real_client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    assert real_client.is_healthy() is True

    # Reset CRM database to clean baseline
    reset_data = real_client.reset_database()
    assert reset_data["status"] == "reset_complete"

    # 2. Before State: Check known customer
    cust_id = "cust-acme-001"
    initial_cust = real_client.get_customer(cust_id)
    assert initial_cust is not None
    assert initial_cust.name == "Acme Corporation"
    assert initial_cust.email == "billing@supplier.com"
    assert initial_cust.status == "PENDING_INVOICE"
    assert initial_cust.invoice_reference == "INV-2026-402"
    assert initial_cust.recent_attachment_sha256 is None

    # 3. Real Executor Step 1: find_customer
    executor = CrmApiExecutor(client=real_client)

    find_step = PlannedStep(
        plan_step_id="step-real-find",
        source_canonical_step_id="c-find",
        source_semantic_step_id="s-find",
        source_dna_step_key="d-find",
        application="CRM",
        action="find_customer",
        description="Find customer by billing email",
        resolved_parameters={"email": "billing@supplier.com"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="CRM lookup",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c-find",
            application="CRM",
            action="find_customer",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Read customer",
            requires_confirmation=False,
        ),
        expected_result="Customer record found",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="ev-1",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="customer",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx_find = ExecutionContext(
        execution_id="exec-real-1",
        workflow_id="wf-real-1",
        execution_plan_id="plan-real-1",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"email": "billing@supplier.com"},
    )

    res_find = executor.execute(find_step, ctx_find)
    assert res_find.status == ExecutionStepStatus.SUCCESS
    assert res_find.output["total_found"] >= 1
    assert res_find.output["matched_customer"]["customer_id"] == cust_id

    # 4. Real Executor Step 2: update_customer_record
    invoice_ref = "INV-2026-999-LIVE"
    attachment_sha = hashlib.sha256(b"dummy_invoice_pdf_content").hexdigest()
    new_status = "Replacement Requested"
    new_notes = "Customer requested replacement"

    update_step = PlannedStep(
        plan_step_id="step-real-update",
        source_canonical_step_id="c-upd",
        source_semantic_step_id="s-upd",
        source_dna_step_key="d-upd",
        application="CRM",
        action="update_customer_record",
        description="Update customer invoice processing status",
        resolved_parameters={
            "customer_id": cust_id,
            "status": new_status,
            "notes": new_notes,
            "invoice_reference": invoice_ref,
            "recent_attachment_sha256": attachment_sha,
        },
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="CRM record update",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c-upd",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="External state update in CRM",
            requires_confirmation=False,
        ),
        expected_result="Customer record updated",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="ev-2",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="PENDING_INVOICE",
            expected_after_state=new_status,
            actual_state="",
        ),
    )

    ctx_update = ExecutionContext(
        execution_id="exec-real-1",
        workflow_id="wf-real-1",
        execution_plan_id="plan-real-1",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={
            "customer_id": cust_id,
            "status": new_status,
            "notes": new_notes,
            "invoice_reference": invoice_ref,
            "recent_attachment_sha256": attachment_sha,
        },
    )

    res_update = executor.execute(update_step, ctx_update)
    assert res_update.status == ExecutionStepStatus.SUCCESS
    assert res_update.output["status"] == "COMPLETED"
    assert res_update.output["customer"]["status"] == new_status

    # 5. Verify live state directly over HTTP from external client
    direct_http_res = httpx.get(f"{live_crm_service}/customers/{cust_id}")
    assert direct_http_res.status_code == 200
    after_data = direct_http_res.json()
    assert after_data["status"] == new_status
    assert after_data["notes"] == new_notes
    assert after_data["invoice_reference"] == invoice_ref
    assert after_data["recent_attachment_sha256"] == attachment_sha

    # 6. Run Independent CRM Verification
    verifier = CrmVerificationStrategy(client=real_client)
    checks = verifier.build_checks(
        execution_id="exec-real-1",
        step=update_step,
        step_result=res_update,
        sandbox_root="",
    )
    assert len(checks) == 1
    chk = checks[0]
    assert chk.check_type == "crm_customer_record_updated"

    # Execute verification (queries live CRM server via GET)
    verified_chk = verifier.verify(chk, sandbox_root="", step_result=res_update)
    assert verified_chk.status == VerificationStatus.VERIFIED
    assert "integrity_evidence" in verified_chk.evidence
    assert verified_chk.evidence["verified_status"] == new_status


# =========================================================================
# 3. Idempotency Test
# =========================================================================
def test_crm_update_idempotency_real_http(live_crm_service):
    """Executing the exact same approved CRM update twice produces identical state without side effects."""
    client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    client.reset_database()

    executor = CrmApiExecutor(client=client)
    cust_id = "cust-acme-001"
    target_status = "Replacement Requested"

    step = PlannedStep(
        plan_step_id="step-idem",
        source_canonical_step_id="c-idem",
        source_semantic_step_id="s-idem",
        source_dna_step_key="d-idem",
        application="CRM",
        action="update_customer_record",
        description="Update status",
        resolved_parameters={"customer_id": cust_id, "status": target_status},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c-idem",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Change",
            requires_confirmation=False,
        ),
        expected_result="Updated",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state=target_status,
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-idem",
        workflow_id="wf-idem",
        execution_plan_id="plan-idem",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"customer_id": cust_id, "status": target_status},
    )

    # First execution
    res1 = executor.execute(step, ctx)
    assert res1.status == ExecutionStepStatus.SUCCESS

    state1 = client.get_customer(cust_id)
    assert state1.status == target_status

    # Second execution (exact same update)
    res2 = executor.execute(step, ctx)
    assert res2.status == ExecutionStepStatus.SUCCESS

    state2 = client.get_customer(cust_id)
    assert state2.status == target_status
    assert state2.customer_id == state1.customer_id
    assert state2.email == state1.email


# =========================================================================
# 4. Dry Run Guarantees: 0 HTTP Requests, 0 DB Writes
# =========================================================================
def test_crm_dry_run_zero_http_requests_and_zero_db_writes(live_crm_service):
    """In dry-run mode, CrmApiExecutor must make 0 HTTP requests and 0 DB writes."""
    client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    client.reset_database()

    # Record baseline state
    cust_id = "cust-acme-001"
    before = client.get_customer(cust_id)
    assert before.status == "PENDING_INVOICE"

    # Set client to an invalid URL to guarantee any attempt to connect would fail
    fake_client = CrmApiClient(base_url="http://127.0.0.1:59999/api/crm")
    executor = CrmApiExecutor(client=fake_client)

    step = PlannedStep(
        plan_step_id="step-dry",
        source_canonical_step_id="c-dry",
        source_semantic_step_id="s-dry",
        source_dna_step_key="d-dry",
        application="CRM",
        action="update_customer_record",
        description="Dry run update",
        resolved_parameters={"customer_id": cust_id, "status": "MUTATION_ATTEMPT"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c-dry",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Change",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx_dry = ExecutionContext(
        execution_id="exec-dry",
        workflow_id="wf-dry",
        execution_plan_id="plan-dry",
        sandbox_root=".",
        execution_mode=ExecutionMode.DRY_RUN,
        dry_run=True,
        resolved_parameters={"customer_id": cust_id, "status": "MUTATION_ATTEMPT"},
    )

    # Dry-run execution must succeed as SIMULATED without throwing connection errors
    res_dry = executor.execute(step, ctx_dry)
    assert res_dry.status == ExecutionStepStatus.SUCCESS
    assert res_dry.output["status"] == "SIMULATED"
    assert res_dry.output["operation"] == "update_customer_record"

    # Live database state is completely unchanged
    after = client.get_customer(cust_id)
    assert after.status == "PENDING_INVOICE"
    assert after.status != "MUTATION_ATTEMPT"


# =========================================================================
# 5. Policy Boundary: Unapproved CRM Workflow Remains BLOCKED
# =========================================================================
def test_unapproved_crm_workflow_remains_blocked(live_crm_service):
    """An unapproved workflow plan containing CRM steps is BLOCKED by ExecutionEngine."""
    client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    client.reset_database()

    workflow_id = "wf-unapproved-crm"
    spec = CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-crm-unapp",
        source_semantic_workflow_id="sem-crm-unapp",
        title="Unapproved CRM Plan",
        intent="Update CRM without approval",
        description="Should be blocked",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="CRM:update_customer_record",
            last_step="CRM:update_customer_record",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=1,
            invariant_evidence="Unapproved CRM",
            variable_evidence="None",
            optional_step_evidence="None",
            ordering_evidence="Single",
            boundary_evidence="Established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.MEDIUM,
            primary_risk_category=RiskCategory.EXTERNAL_CHANGE,
            requires_human_confirmation=True,
            step_risks=[],
            summary="Medium risk",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.REQUIRES_REVIEW,  # NOT approved!
            reviewed_by="",
            comments="",
        ),
    )
    CanonicalWorkflowRepository().save(spec)

    step = PlannedStep(
        plan_step_id="step-unapproved",
        source_canonical_step_id="c-unapp",
        source_semantic_step_id="s-unapp",
        source_dna_step_key="d-unapp",
        application="CRM",
        action="update_customer_record",
        description="Unauthorized update",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "HACKED"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c-unapp",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="External change",
            requires_confirmation=True,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=True,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    plan = ExecutionPlan(
        execution_plan_id="plan-unapproved-crm",
        source_workflow_id=workflow_id,
        workflow_version="1.0.0",
        source_approval_state="pending",
        resolved_parameters=[],
        planned_steps=[step],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="step-unapproved",
            last_step="step-unapproved",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        risk_assessment={
            "overall_risk_level": "medium",
            "primary_risk_category": "external_change",
            "requires_human_confirmation": True,
            "summary": "Unapproved",
        },
        expected_effects=[],
        dry_run_status="NOT_RUN",
    )
    ExecutionPlanRepository().save(plan)

    reg = ExecutorRegistry()
    reg.register(CrmApiExecutor(client=client))
    engine = ExecutionEngine(registry=reg)

    # Execution is safely rejected / BLOCKED by policy
    with pytest.raises(ValueError, match="rejected by security policy"):
        engine.execute_plan("plan-unapproved-crm")

    # Confirm CRM state is untouched
    cust = client.get_customer("cust-acme-001")
    assert cust.status != "HACKED"


# =========================================================================
# 6. Failure Handling (Offline, Invalid Customer, State Mismatch)
# =========================================================================
def test_crm_executor_fails_safely_when_server_offline():
    """When the CRM server is offline, CrmApiExecutor returns FAILED with clear message."""
    dead_client = CrmApiClient(base_url="http://127.0.0.1:59999/api/crm", timeout=1.0)
    executor = CrmApiExecutor(client=dead_client)

    step = PlannedStep(
        plan_step_id="step-fail-offline",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Update on dead server",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "FAILED_ATTEMPT"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Risk",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-fail-1",
        workflow_id="wf-fail-1",
        execution_plan_id="plan-fail-1",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"customer_id": "cust-acme-001", "status": "FAILED_ATTEMPT"},
    )

    res = executor.execute(step, ctx)
    assert res.status == ExecutionStepStatus.FAILED
    assert "CRM API unavailable" in res.error


def test_crm_executor_fails_when_customer_not_found(live_crm_service):
    """CrmApiExecutor returns FAILED when customer does not exist in CRM."""
    client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    executor = CrmApiExecutor(client=client)

    step = PlannedStep(
        plan_step_id="step-fail-404",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Update non-existent customer",
        resolved_parameters={"customer_id": "cust-ghost-999", "status": "UPDATED"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Risk",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-404",
        workflow_id="wf-404",
        execution_plan_id="plan-404",
        sandbox_root=".",
        execution_mode=ExecutionMode.LIVE,
        resolved_parameters={"customer_id": "cust-ghost-999", "status": "UPDATED"},
    )

    res = executor.execute(step, ctx)
    assert res.status == ExecutionStepStatus.FAILED
    assert "not found" in res.error.lower()


def test_crm_verification_fails_on_state_mismatch(live_crm_service):
    """CrmVerificationStrategy detects if CRM server state diverges from expected values."""
    client = CrmApiClient(base_url=live_crm_service, timeout=5.0)
    client.reset_database()

    verifier = CrmVerificationStrategy(client=client)

    step = PlannedStep(
        plan_step_id="step-mismatch",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Update",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "EXPECTED_STATUS"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Risk",
            requires_confirmation=False,
        ),
        expected_result="",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="",
            expected_after_state="EXPECTED_STATUS",
            actual_state="",
        ),
    )

    # Step result claims it updated to EXPECTED_STATUS
    step_result = ExecutionStepResult(
        planned_step_id="step-mismatch",
        action_name="update_customer_record",
        target_application="CRM",
        strategy=ExecutionStrategy.API,
        executor_name="CrmApiExecutor",
        status=ExecutionStepStatus.SUCCESS,
        parameters_used={"customer_id": "cust-acme-001", "status": "EXPECTED_STATUS"},
        output={
            "operation": "update_customer_record",
            "customer_id": "cust-acme-001",
            "updated_fields": {"status": "EXPECTED_STATUS"},
            "status": "COMPLETED",
        },
        affected_resources=["crm:customer:cust-acme-001"],
    )

    checks = verifier.build_checks("exec-mm", step, step_result, sandbox_root="")
    chk = checks[0]

    # But the live database still has status 'PENDING_INVOICE'
    evaluated = verifier.verify(chk, sandbox_root="", step_result=step_result)
    assert evaluated.status == VerificationStatus.FAILED
    assert "state mismatch" in evaluated.reason.lower()
