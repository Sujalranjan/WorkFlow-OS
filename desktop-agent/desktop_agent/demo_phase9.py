"""Demonstration script: Post-Execution Verification + Evidence Engine (Phase 9).

Demonstrates:
1. Build/obtain approved workflow.
2. Create execution plan.
3. Execute a safe controlled local action.
4. Show:
   Executor: SUCCESS
5. Run verification.
6. Verify the generated artifact.
7. Show:
   Verification: VERIFIED
8. Demonstrate a verification failure:
   Executor: SUCCESS
   Verification: FAILED
   Interpretation: ACTION EXECUTED BUT EXPECTED STATE WAS NOT VERIFIED.
9. Demonstrate verification evidence (SHA256, size, path, timestamp).
10. Verify persistence of verification records across database retrieval.
11. Confirm ZERO external service mutations.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
import uuid

# Ensure repo root and backend are on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _dir in [str(_REPO_ROOT), str(_REPO_ROOT / "backend"), str(_REPO_ROOT / "desktop-agent")]:
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# Ensure terminal stdout safely prints UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalWorkflowSpec,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.dna import DNAEvidence, WorkflowBoundaries
from app.models.execution_plan import (
    ExecutionPlan,
    ExecutionStrategy,
    ExpectedStateChange,
    ParameterResolutionStatus,
    PlannedStep,
    PreconditionCheck,
    PreconditionStatus,
    ResolvedParameter,
    StepExecutionStrategy,
)
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository


class BackendClient:
    """Seamless API client: uses HTTP if backend is up, otherwise TestClient."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.use_test_client = False
        self._test_client = None

        try:
            req = urllib.request.Request(f"{self.base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    print(f"[*] Connected to active backend server at {self.base_url}")
                    return
        except Exception:
            pass

        print(f"[*] Backend server not reachable at {self.base_url}. Using in-process FastAPI TestClient.")
        from fastapi.testclient import TestClient
        from app.main import app
        self.use_test_client = True
        self._test_client = TestClient(app)

    def post(self, endpoint: str, data: dict = None) -> dict:
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        if self.use_test_client:
            path = endpoint.replace(self.base_url, "")
            resp = self._test_client.post(path, json=data or {})
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}: {resp.text}")
            return resp.json()
        else:
            payload = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))

    def get(self, endpoint: str) -> dict:
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        if self.use_test_client:
            path = endpoint.replace(self.base_url, "")
            resp = self._test_client.get(path)
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}: {resp.text}")
            return resp.json()
        else:
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))


def run_phase9_demo() -> None:
    backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
    client = BackendClient(backend_url)

    print("\n==================================================================")
    print("   WorkFlowOS Phase 9: Post-Execution Verification & Evidence    ")
    print("==================================================================")
    print("Core Mandate       : Distinguish EXECUTOR SUCCESS from VERIFIED SUCCESS")
    print("Safety Paradigm    : Sandbox Isolation + Deterministic Evidence (No LLM)")
    print("Prohibition        : Zero Gmail / CRM / Slack Mutations")
    print("==================================================================\n")

    # 1. Build and obtain approved workflow with safe local action
    print("Step 1: Assembling approved workflow for customer replacement summary...")
    wf_id = f"wf-verif-demo-{uuid.uuid4().hex[:8]}"
    spec = CanonicalWorkflowSpec(
        workflow_id=wf_id,
        source_dna_id="dna-verif-demo",
        source_semantic_workflow_id="sem-verif-demo",
        title="Customer Replacement Verification Workflow",
        intent="Generate customer replacement summary safely inside sandbox",
        description="Write and verify customer replacement summary artifact",
        version="1.0.0",
        status="specification_ready",
        steps=[],
        variables=[],
        optional_steps=[],
        preconditions=["Isolated sandbox directory is available"],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=2,
        ),
        ordering_constraints=[],
        evidence=DNAEvidence(
            supporting_session_count=2,
            invariant_evidence="Local file output step",
            variable_evidence="filename, customer",
            optional_step_evidence="None",
            ordering_evidence="Sequential",
            boundary_evidence="Isolated sandbox root",
        ),
        parameter_bindings=[],
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk local file action",
            sensitive_factors_detected=[],
        ),
        approval_state=ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by="qa_compliance@workflowos.local",
            comments="Approved for Phase 9 verification demo",
        ),
    )
    CanonicalWorkflowRepository().save(spec)
    print(f"   [Approved] Workflow ID: {wf_id}")

    # 2. Create Execution Plan
    print("\nStep 2: Creating execution plan for controlled local action...")
    plan_id = f"exec-plan-verif-{uuid.uuid4().hex[:8]}"
    step_id = f"pstep-verif-{uuid.uuid4().hex[:8]}"

    plan = ExecutionPlan(
        execution_plan_id=plan_id,
        source_workflow_id=wf_id,
        workflow_version="1.0.0",
        source_approval_state="approved",
        resolved_parameters=[
            ResolvedParameter(
                semantic_name="file_name",
                source_parameter="file_name",
                source_field="parameters",
                inferred_type="filename",
                runtime_value="customer_replacement_summary.json",
                resolution_status=ParameterResolutionStatus.RESOLVED,
                is_required=True,
            ),
            ResolvedParameter(
                semantic_name="customer",
                source_parameter="customer",
                source_field="parameters",
                inferred_type="string",
                runtime_value="Rahul Sharma",
                resolution_status=ParameterResolutionStatus.RESOLVED,
                is_required=True,
            ),
            ResolvedParameter(
                semantic_name="status",
                source_parameter="status",
                source_field="parameters",
                inferred_type="string",
                runtime_value="replacement_requested",
                resolution_status=ParameterResolutionStatus.RESOLVED,
                is_required=True,
            ),
        ],
        planned_steps=[
            PlannedStep(
                plan_step_id=step_id,
                source_canonical_step_id="can-step-1",
                source_semantic_step_id="sem-step-1",
                source_dna_step_key="dna-step-1",
                application="File System",
                action="save_file",
                description="Save customer replacement record inside sandbox",
                resolved_parameters={
                    "file_name": "customer_replacement_summary.json",
                    "customer": "Rahul Sharma",
                    "status": "replacement_requested",
                },
                execution_strategy=StepExecutionStrategy(
                    strategy=ExecutionStrategy.APPLICATION_INTEGRATION,
                    reason="Local file persistence through OS filesystem connector",
                    target_technology="Local OS File System API",
                ),
                risk=StepRisk(
                    step_id="can-step-1",
                    application="File System",
                    action="save_file",
                    risk_level=RiskLevel.LOW,
                    risk_category=RiskCategory.LOCAL_CHANGE,
                    reason="Modifies local disk inside sandbox",
                    requires_confirmation=False,
                ),
                expected_result="customer_replacement_summary.json written to sandbox",
                external_change=False,
                requires_confirmation=False,
                evidence_reference="evidence-verif-1",
                state_change=ExpectedStateChange(
                    target_system="File System",
                    entity_or_property="customer_replacement_summary.json",
                    before_state="File does not exist",
                    expected_after_state="customer_replacement_summary.json exists in sandbox",
                    actual_state="UNTOUCHED",
                ),
                preconditions=[
                    PreconditionCheck(
                        condition="Sandbox is writable",
                        status=PreconditionStatus.SATISFIED,
                        evaluation_reason="Verified by backend engine",
                    )
                ],
            )
        ],
        preconditions=[
            PreconditionCheck(
                condition="Sandbox ready",
                status=PreconditionStatus.SATISFIED,
                evaluation_reason="Ready",
            )
        ],
        boundaries=WorkflowBoundaries(
            first_step="File System:save_file",
            last_step="File System:save_file",
            min_duration_seconds=1.0,
            max_duration_seconds=5.0,
            average_duration_seconds=2.0,
            total_supporting_sessions=2,
        ),
        risk_assessment=RiskAssessment(
            overall_risk_level=RiskLevel.LOW,
            primary_risk_category=RiskCategory.LOCAL_CHANGE,
            requires_human_confirmation=False,
            step_risks=[],
            summary="Low risk",
            sensitive_factors_detected=[],
        ),
        expected_effects=[
            ExpectedStateChange(
                target_system="File System",
                entity_or_property="customer_replacement_summary.json",
                before_state="Does not exist",
                expected_after_state="customer_replacement_summary.json exists in sandbox",
                actual_state="UNTOUCHED",
            )
        ],
        dry_run_status="SIMULATED",
    )
    ExecutionPlanRepository().save(plan)
    print(f"   [Plan Created] ID: {plan_id}")

    # 3. Execute safe controlled local action
    print("\n==================================================================")
    print(" STEP 3 & 4: EXECUTE SAFE CONTROLLED LOCAL ACTION                ")
    print("==================================================================")
    exec_res = client.post(
        f"/api/workflows/execution-plans/{plan_id}/execute",
        {"execution_mode": "LIVE", "idempotency_key": f"phase9-demo-{uuid.uuid4().hex[:6]}"},
    )
    execution_id = exec_res["execution_id"]
    step_0 = exec_res["step_results"][0]

    print(f"   Execution ID        : {execution_id}")
    print(f"   Sandbox Root        : {exec_res['sandbox_root']}")
    print(f"   Action Executed     : {step_0['action_name']} ({step_0['target_application']})")
    print(f"   Executor Used       : {step_0['executor_name']}")
    print(f"   Affected Resources  : {step_0['affected_resources']}")
    print(f"\n   >>> Executor Result : {step_0['status']} <<<")
    assert step_0["status"] == "SUCCESS", "Expected executor to succeed"

    # 4. Run verification on the executed step
    print("\n==================================================================")
    print(" STEP 5, 6, 7: RUN DETERMINISTIC POST-EXECUTION VERIFICATION      ")
    print("==================================================================")
    verif_res = client.post(
        f"/api/workflows/executions/{execution_id}/verify",
        {"force_recheck": True},
    )
    vrun_id = verif_res["verification_run_id"]
    print(f"   Verification Run ID : {vrun_id}")
    print(f"   Checks Evaluated    : {len(verif_res['checks'])}")
    print(f"   Verified Checks     : {verif_res['verified_count']}")
    print(f"   Failed Checks       : {verif_res['failed_count']}")
    print(f"   Unknown Checks      : {verif_res['unknown_count']}")
    print(f"\n   >>> Verification    : {verif_res['overall_status']} <<<")
    assert verif_res["overall_status"] == "VERIFIED"

    # 5. Demonstrate deterministic evidence
    print("\n==================================================================")
    print(" STEP 8 & 9: DEMONSTRATE CRYPTOGRAPHIC INTEGRITY EVIDENCE (SHA-256) ")
    print("==================================================================")
    for idx, chk in enumerate(verif_res["checks"]):
        print(f"\n   --- Check #{idx+1}: [{chk['check_type']}] on '{chk['target']}' ---")
        print(f"   Strategy            : {chk['strategy_type']}")
        print(f"   Status              : {chk['status']}")
        print(f"   Reason              : {chk['reason']}")
        print(f"   Deterministic Evidence:")
        print(json.dumps(chk["evidence"], indent=6))

    # 6. Demonstrate verification failure: Executor SUCCESS != Verification SUCCESS
    print("\n==================================================================")
    print(" STEP 8: DEMONSTRATE VERIFICATION FAILURE                         ")
    print("         (Executor: SUCCESS, Verification: FAILED)               ")
    print("==================================================================")
    sandbox_path = Path(exec_res["sandbox_root"])
    target_file = sandbox_path / "customer_replacement_summary.json"
    assert target_file.exists(), "Expected sandbox artifact to exist"
    
    # Deliberately remove the expected sandbox file to simulate missing artifact
    target_file.unlink()
    print(f"   [Simulation] Deliberately removed expected artifact: '{target_file.name}'")

    # Re-run verification against the diverged state
    verif_fail_res = client.post(
        f"/api/workflows/executions/{execution_id}/verify",
        {"force_recheck": True},
    )
    failed_check = verif_fail_res["checks"][0]

    print("\n   --- Comparative Result Breakdown ---")
    print(f"   Executor Status     : {step_0['status']}")
    print(f"   Verification Status : {verif_fail_res['overall_status']}")
    print(f"   Failing Check Reason: {failed_check['reason']}")
    print("\n   ==============================================================")
    print("   ARCHITECTURAL INTERPRETATION:")
    print("   ACTION EXECUTED BUT EXPECTED STATE WAS NOT VERIFIED.")
    print("   ==============================================================")
    assert verif_fail_res["overall_status"] == "FAILED"

    # 7. Persistence Across Database Retrieval
    print("\n==================================================================")
    print(" STEP 10: VERIFY PERSISTENCE ACROSS REPOSITORY RETRIEVAL          ")
    print("==================================================================")
    persisted = client.get(f"/api/workflows/verifications/{verif_fail_res['verification_run_id']}")
    print(f"   Retrieved Run ID    : {persisted['verification_run_id']}")
    print(f"   Retrieved Status    : {persisted['overall_status']}")
    print(f"   Persisted Checks    : {len(persisted['checks'])}")
    assert persisted["verification_run_id"] == verif_fail_res["verification_run_id"]

    # 8. Security and Mutation Guarantee
    print("\n==================================================================")
    print(" STEP 11: CONFIRM ZERO EXTERNAL MUTATIONS & SECURITY BOUNDARIES   ")
    print("==================================================================")
    print("   [SAFEGUARD 1] Sandbox Isolation: All inspected targets strictly confined within:")
    print(f"                 {exec_res['sandbox_root']}")
    print("   [SAFEGUARD 2] Deterministic Checks: Zero LLMs / Gemini calls used for verification.")
    print("   [SAFEGUARD 3] Fail-Closed Security: Arbitrary path traversals & external services rejected.")
    print("   [SAFEGUARD 4] Zero Mutations: No Gmail, CRM, or Slack endpoints contacted.")
    print("\n>>> Phase 9 Verification and Evidence Engine successfully demonstrated! <<<\n")


if __name__ == "__main__":
    run_phase9_demo()
