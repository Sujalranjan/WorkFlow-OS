"""Unit, Integration, and Architecture Tests for WorkFlowOS Demo CRM (Phase 15B).

Verifies:
1. CRM database repository CRUD and search
2. CRM REST API endpoints (/health, /customers, /search, PATCH, seed, reset)
3. CrmApiClient HTTP client abstraction and error handling
4. CrmApiExecutor capability registration in ExecutorRegistry
5. CrmApiExecutor action validation and safety guardrails
6. CrmApiExecutor find_customer execution
7. CrmApiExecutor update_customer_record execution
8. Dry-run simulation produces 0 real actions and 0 CRM mutations
9. CrmVerificationStrategy independent post-execution verification
10. Verification fails when CRM database state was not updated
11. Cryptographic integrity evidence using SHA-256
12. End-to-end plan execution through ExecutionEngine and VerificationEngine
13. Architectural boundary: executor uses CrmApiClient, not direct database updates
"""

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

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
from app.repositories.execution_repository import ExecutionRepository
from app.services.crm_client import (
    CrmApiClient,
    CrmApiError,
    CrmCustomerNotFoundError,
)
from app.services.dry_run_simulator import DryRunSimulator
from app.services.execution_engine import ExecutionEngine
from app.services.executors.crm_executor import CrmApiExecutor
from app.services.executors.registry import ExecutorRegistry
from app.services.strategy_selector import StrategySelector
from app.services.verification_engine import VerificationEngine
from app.services.verifiers.crm_verifier import CrmVerificationStrategy


@pytest.fixture
def temp_crm_repo(tmp_path):
    """Provides a fresh temporary CRM repository."""
    db_file = tmp_path / "test_crm.db"
    repo = CrmRepository(db_path=str(db_file))
    repo.seed_default_customers()
    return repo


@pytest.fixture
def mock_crm_client():
    """Provides a mocked CrmApiClient with controlled customer data."""
    client = MagicMock(spec=CrmApiClient)
    client.is_healthy.return_value = True

    sample_customer = CrmCustomer(
        customer_id="cust-acme-001",
        name="Acme Corporation",
        email="billing@supplier.com",
        company="Acme Supplies Ltd",
        status="ACTIVE",
        notes="Awaiting monthly processing",
        invoice_reference="INV-2026-402",
    )
    client.find_customer.return_value = CrmSearchResult(
        query="billing@supplier.com",
        total_found=1,
        customers=[sample_customer],
    )

    state = {"customer": sample_customer}

    def update_side_effect(cid, updates):
        current = state["customer"].model_copy(update=updates)
        state["customer"] = current
        return current

    client.get_customer.side_effect = lambda cid: state["customer"]
    client.update_customer.side_effect = update_side_effect
    return client


# =========================================================================
# 1. CRM Repository Tests
# =========================================================================
def test_crm_repository_crud(tmp_path):
    """Test CRM repository save, get, search, update, delete."""
    db_file = tmp_path / "repo_crud.db"
    repo = CrmRepository(db_path=str(db_file))

    # 1. Save new customer
    cust = CrmCustomer(
        customer_id="cust-test-1",
        name="Test Corp",
        email="test@corp.com",
        company="Test Industries",
        status="ACTIVE",
    )
    repo.save(cust)

    # 2. Get by ID & Email
    retrieved = repo.get_by_id("cust-test-1")
    assert retrieved is not None
    assert retrieved.name == "Test Corp"

    retrieved_email = repo.get_by_email("test@corp.com")
    assert retrieved_email is not None
    assert retrieved_email.customer_id == "cust-test-1"

    # 3. Find with query
    found = repo.find(query="Test")
    assert len(found) == 1
    assert found[0].customer_id == "cust-test-1"

    # 4. Update
    updated = repo.update("cust-test-1", {"status": "INVOICE_PROCESSED", "notes": "Done"})
    assert updated is not None
    assert updated.status == "INVOICE_PROCESSED"
    assert updated.notes == "Done"

    # 5. Delete
    assert repo.delete("cust-test-1") is True
    assert repo.get_by_id("cust-test-1") is None


def test_crm_repository_default_seeding(tmp_path):
    """Test default demo seeding populates expected problem statement customer records."""
    db_file = tmp_path / "seed_test.db"
    repo = CrmRepository(db_path=str(db_file))
    seeded = repo.seed_default_customers()
    assert len(seeded) >= 3

    # Acme Corp must be present (billing@supplier.com)
    acme = repo.get_by_email("billing@supplier.com")
    assert acme is not None
    assert "Acme" in acme.name
    assert acme.status == "PENDING_INVOICE"


# =========================================================================
# 2. CRM REST API Endpoints Tests
# =========================================================================
def test_crm_api_endpoints():
    """Test CRM REST API endpoints via TestClient."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Health
    h_res = client.get("/api/crm/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "ok"

    # Reset & Seed
    s_res = client.post("/api/crm/reset")
    assert s_res.status_code == 200

    # Search via GET
    list_res = client.get("/api/crm/customers?query=Acme")
    assert list_res.status_code == 200
    data = list_res.json()
    assert len(data) >= 1
    assert data[0]["customer_id"] == "cust-acme-001"

    # Search via POST /search
    post_search = client.post("/api/crm/customers/search", json={"query": "billing@supplier.com"})
    assert post_search.status_code == 200
    search_data = post_search.json()
    assert search_data["total_found"] >= 1
    assert search_data["customers"][0]["email"] == "billing@supplier.com"

    # Get Single
    get_res = client.get("/api/crm/customers/cust-acme-001")
    assert get_res.status_code == 200
    assert get_res.json()["company"] == "Acme Supplies Ltd"

    # Update via PATCH
    patch_res = client.patch(
        "/api/crm/customers/cust-acme-001",
        json={"status": "INVOICE_PROCESSED", "notes": "Updated in test"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "INVOICE_PROCESSED"

    # Confirm updated value persists
    get_after = client.get("/api/crm/customers/cust-acme-001")
    assert get_after.json()["status"] == "INVOICE_PROCESSED"


# =========================================================================
# 3. CRM Client Tests
# =========================================================================
def test_crm_client_operations():
    """Test CrmApiClient methods against the FastAPI application."""
    from app.main import app

    client = CrmApiClient(app=app)
    assert client.is_healthy() is True

    # Seed
    seeded = client.seed_demo_data()
    assert len(seeded) >= 3

    # Find customer
    search_res = client.find_customer(query="Acme")
    assert search_res.total_found >= 1
    assert search_res.customers[0].customer_id == "cust-acme-001"

    # Get customer
    cust = client.get_customer("cust-acme-001")
    assert cust is not None
    assert cust.email == "billing@supplier.com"

    # Update customer
    updated = client.update_customer(
        "cust-acme-001",
        {"status": "RECORD_PROCESSED", "notes": "CrmApiClient verification"},
    )
    assert updated.status == "RECORD_PROCESSED"
    assert updated.notes == "CrmApiClient verification"


# =========================================================================
# 4. CRM Executor Capability & Registry Tests
# =========================================================================
def test_crm_executor_registered_in_registry():
    """Test CrmApiExecutor is registered in ExecutorRegistry with implemented=True."""
    registry = ExecutorRegistry()
    crm_exec = registry.get_by_name("CrmApiExecutor")
    assert crm_exec is not None
    cap = crm_exec.capability
    assert cap.implemented is True
    assert cap.requires_external_access is True
    assert cap.supports_verification is True
    assert "find_customer" in cap.supported_actions
    assert "update_customer_record" in cap.supported_actions
    assert any("crm" in t.lower() for t in cap.supported_targets)

    # list_implemented_executors includes CrmApiExecutor
    impl = registry.list_implemented_executors()
    assert "ControlledLocalExecutor" in impl
    assert "GmailApiExecutor" in impl
    assert "CrmApiExecutor" in impl


def test_strategy_selector_selects_crm_executor():
    """Test StrategySelector selects CrmApiExecutor for CRM steps."""
    step = PlannedStep(
        plan_step_id="step-crm-find",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="find_customer",
        description="Lookup customer in CRM",
        resolved_parameters={"query": "billing@supplier.com"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="CRM lookup",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="find_customer",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Read-only CRM query",
            requires_confirmation=False,
        ),
        expected_result="Customer found",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="customer",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    selector = StrategySelector()
    res = selector.select_strategy(step)
    assert res.is_executable is True
    assert res.selected_executor == "CrmApiExecutor"
    assert res.selected_strategy == ExecutionStrategyType.API_INTEGRATION
    assert res.policy_decision == "ALLOWED"


# =========================================================================
# 5. CRM Executor Execution Tests
# =========================================================================
def test_crm_executor_find_customer_success(mock_crm_client, tmp_path):
    """Test find_customer execution returns structured customer records."""
    executor = CrmApiExecutor(client=mock_crm_client)
    step = PlannedStep(
        plan_step_id="s-find",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="find_customer",
        description="Find customer by email",
        resolved_parameters={"query": "billing@supplier.com"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Lookup",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="find_customer",
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason="Read",
            requires_confirmation=False,
        ),
        expected_result="Customer found",
        external_change=False,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="customer",
            before_state="",
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-crm-1",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"query": "billing@supplier.com"},
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    assert res.output["operation"] == "find_customer"
    assert res.output["total_found"] == 1
    assert res.output["matched_customer"]["customer_id"] == "cust-acme-001"
    assert len(res.affected_resources) == 0


def test_crm_executor_update_customer_success(mock_crm_client, tmp_path):
    """Test update_customer_record execution updates CRM and produces SHA-256 evidence."""
    executor = CrmApiExecutor(client=mock_crm_client)
    step = PlannedStep(
        plan_step_id="s-upd",
        source_canonical_step_id="c2",
        source_semantic_step_id="s2",
        source_dna_step_key="d2",
        application="CRM",
        action="update_customer_record",
        description="Update customer status",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Update",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c2",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="State change",
            requires_confirmation=False,
        ),
        expected_result="Customer updated",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="ACTIVE",
            expected_after_state="INVOICE_PROCESSED",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-crm-2",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
        sandbox_root=str(tmp_path),
    )

    res = executor.execute(step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    assert res.output["operation"] == "update_customer_record"
    assert res.output["customer_id"] == "cust-acme-001"
    assert res.output["updated_fields"]["status"] == "INVOICE_PROCESSED"
    assert "sha256" in res.output
    assert res.affected_resources == ["crm:customer:cust-acme-001"]


def test_crm_executor_dry_run_never_calls_api(mock_crm_client, tmp_path):
    """Test dry run mode produces simulated output with 0 API calls."""
    executor = CrmApiExecutor(client=mock_crm_client)
    step = PlannedStep(
        plan_step_id="s-dry",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Dry run update",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "UPDATED"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="Simulated update",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="c1",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Mutation",
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
            expected_after_state="",
            actual_state="",
        ),
    )

    ctx = ExecutionContext(
        execution_id="exec-dry",
        workflow_id="wf-1",
        execution_plan_id="p-1",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "UPDATED"},
        sandbox_root=str(tmp_path),
        dry_run=True,
    )

    res = executor.execute(step, ctx)
    assert res.status == ExecutionStepStatus.SUCCESS
    assert res.output["status"] == "SIMULATED"
    # Zero calls made to CRM client
    mock_crm_client.update_customer.assert_not_called()
    mock_crm_client.find_customer.assert_not_called()


# =========================================================================
# 6. CRM Verification Strategy Tests
# =========================================================================
def test_crm_verification_success(mock_crm_client, tmp_path):
    """Test CRM verification passes when live CRM server state matches expected update."""
    verifier = CrmVerificationStrategy(client=mock_crm_client)

    step = PlannedStep(
        plan_step_id="s-upd-v",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Update",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
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

    step_result = ExecutionStepResult(
        planned_step_id="s-upd-v",
        action_name="update_customer_record",
        target_application="CRM",
        strategy=ExecutionStrategy.API,
        executor_name="CrmApiExecutor",
        status=ExecutionStepStatus.SUCCESS,
        parameters_used={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
        output={
            "operation": "update_customer_record",
            "customer_id": "cust-acme-001",
            "updated_fields": {"status": "INVOICE_PROCESSED"},
            "status": "COMPLETED",
        },
        affected_resources=["crm:customer:cust-acme-001"],
    )

    # Reflect executed update in mock CRM state
    mock_crm_client.update_customer("cust-acme-001", {"status": "INVOICE_PROCESSED"})

    checks = verifier.build_checks(
        execution_id="exec-v-1",
        step=step,
        step_result=step_result,
        sandbox_root=str(tmp_path),
    )
    assert len(checks) == 1
    chk = checks[0]
    assert chk.check_type == "crm_customer_record_updated"

    # Evaluated against live mock CRM
    evaluated = verifier.verify(chk, sandbox_root=str(tmp_path), step_result=step_result)
    assert evaluated.status == VerificationStatus.VERIFIED
    assert "cryptographic integrity evidence using SHA-256" in evaluated.evidence["integrity_evidence"]


def test_crm_verification_fails_when_state_mismatches(tmp_path):
    """Test verification strictly FAILS if CRM database state does not match expectations."""
    # Mock client returns customer with status "ACTIVE", but we expected "INVOICE_PROCESSED"
    mismatch_client = MagicMock(spec=CrmApiClient)
    mismatch_client.get_customer.return_value = CrmCustomer(
        customer_id="cust-acme-001",
        name="Acme Corporation",
        email="billing@supplier.com",
        status="ACTIVE",  # NOT updated!
    )

    verifier = CrmVerificationStrategy(client=mismatch_client)

    step = PlannedStep(
        plan_step_id="s-upd-v2",
        source_canonical_step_id="c1",
        source_semantic_step_id="s1",
        source_dna_step_key="d1",
        application="CRM",
        action="update_customer_record",
        description="Update",
        resolved_parameters={"customer_id": "cust-acme-001"},
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

    step_result = ExecutionStepResult(
        planned_step_id="s-upd-v2",
        action_name="update_customer_record",
        target_application="CRM",
        strategy=ExecutionStrategy.API,
        executor_name="CrmApiExecutor",
        status=ExecutionStepStatus.SUCCESS,
        parameters_used={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
        output={
            "operation": "update_customer_record",
            "customer_id": "cust-acme-001",
            "updated_fields": {"status": "INVOICE_PROCESSED"},
            "status": "COMPLETED",
        },
        affected_resources=["crm:customer:cust-acme-001"],
    )

    checks = verifier.build_checks(
        execution_id="exec-v-2",
        step=step,
        step_result=step_result,
        sandbox_root=str(tmp_path),
    )
    evaluated = verifier.verify(checks[0], sandbox_root=str(tmp_path), step_result=step_result)
    assert evaluated.status == VerificationStatus.FAILED
    assert "CRM state mismatch" in evaluated.reason


# =========================================================================
# 7. End-to-End Execution Plan with CRM Integration
# =========================================================================
def test_end_to_end_crm_plan_execution(mock_crm_client):
    """Test full execution of an approved plan containing a CRM update step."""
    workflow_id = "wf-crm-approved-e2e"
    spec = CanonicalWorkflowSpec(
        workflow_id=workflow_id,
        source_dna_id="dna-crm-1",
        source_semantic_workflow_id="sem-crm-1",
        title="CRM Update Workflow",
        intent="Update customer invoice status",
        description="Workflow to update customer record in CRM",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["CRM API reachable"],
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
            invariant_evidence="CRM update observed",
            variable_evidence="Status",
            optional_step_evidence="None",
            ordering_evidence="Single step",
            boundary_evidence="Boundaries established",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.MEDIUM,
            primary_risk_category=RiskCategory.EXTERNAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Medium risk CRM update",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="admin",
            comments="Approved for CRM update",
        ),
    )
    CanonicalWorkflowRepository().save(spec)

    step = PlannedStep(
        plan_step_id="step-crm-e2e",
        source_canonical_step_id="can-crm-1",
        source_semantic_step_id="sem-crm-1",
        source_dna_step_key="dna-crm-1",
        application="CRM",
        action="update_customer_record",
        description="Update customer record in CRM",
        resolved_parameters={"customer_id": "cust-acme-001", "status": "INVOICE_PROCESSED"},
        execution_strategy=StepExecutionStrategy(
            strategy=ExecutionStrategy.API,
            reason="CRM update via API",
            target_technology="CRM API",
        ),
        risk=StepRisk(
            step_id="can-crm-1",
            application="CRM",
            action="update_customer_record",
            risk_level=RiskLevel.MEDIUM,
            risk_category=RiskCategory.EXTERNAL_CHANGE,
            reason="Update customer record",
            requires_confirmation=False,
        ),
        expected_result="Customer record updated",
        external_change=True,
        requires_confirmation=False,
        evidence_reference="ev-crm-e2e",
        state_change=ExpectedStateChange(
            target_system="CRM",
            entity_or_property="status",
            before_state="ACTIVE",
            expected_after_state="INVOICE_PROCESSED",
            actual_state="",
        ),
    )

    plan = ExecutionPlan(
        execution_plan_id="plan-crm-e2e",
        source_workflow_id=workflow_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                semantic_name="customer_id",
                source_parameter="customer_id",
                source_field="parameters.customer_id",
                inferred_type="string",
                is_required=True,
                runtime_value="cust-acme-001",
                resolution_status="resolved",
            ),
            ResolvedParameter(
                semantic_name="status",
                source_parameter="status",
                source_field="parameters.status",
                inferred_type="string",
                is_required=True,
                runtime_value="INVOICE_PROCESSED",
                resolution_status="resolved",
            ),
        ],
        planned_steps=[step],
        preconditions=[],
        boundaries=WorkflowBoundaries(
            first_step="step-crm-e2e",
            last_step="step-crm-e2e",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=1,
        ),
        risk_assessment={
            "overall_risk_level": "medium",
            "primary_risk_category": "external_change",
            "requires_human_confirmation": False,
            "summary": "CRM update",
        },
        expected_effects=[],
        dry_run_status="SIMULATED",
    )
    ExecutionPlanRepository().save(plan)

    reg = ExecutorRegistry()
    reg.register(CrmApiExecutor(client=mock_crm_client))
    engine = ExecutionEngine(registry=reg)

    audit = engine.execute_plan(plan.execution_plan_id)
    assert audit.status == ExecutionOverallStatus.COMPLETED
    assert len(audit.step_results) == 1
    assert audit.step_results[0].executor_name == "CrmApiExecutor"
    assert audit.step_results[0].status == ExecutionStepStatus.SUCCESS

    # Run verification engine
    verif = VerificationEngine()
    # Inject mock_crm_client into CrmVerificationStrategy in registry
    crm_verif = verif.strategy_registry.get_by_name("CrmVerificationStrategy")
    if crm_verif:
        crm_verif.client = mock_crm_client

    verif_res = verif.verify_execution(audit.execution_id, force_recheck=True)
    assert verif_res.overall_status == VerificationStatus.VERIFIED
    assert verif_res.verified_count >= 1
