"""Phase 16: Full End-to-End Workflow Definition and Orchestrator.

Orchestrates the hackathon problem statement's core routine:
Gmail search_email
    ↓
Gmail download_attachment
    ↓
CRM find_customer
    ↓
CRM update_customer_record
    ↓
Slack send_notification
    ↓
Independent verification (Gmail, FileSystem, CRM, Slack)
    ↓
Deterministic Learning
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    ParameterBinding,
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
    VariableType,
)
from app.models.dna import DNAEvidence, WorkflowBoundaries
from app.models.execution import ExecutionAuditRecord, ExecutionMode, ExecutionOverallStatus
from app.models.execution_plan import ExecutionPlan
from app.models.learning import WorkflowReliabilityProfile
from app.models.verification import VerificationResult
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.learning_engine import LearningEngine
from app.services.verification_engine import VerificationEngine


def build_phase16_canonical_spec(
    workflow_id: Optional[str] = None,
    approval_state: ApprovalState = ApprovalState.REQUIRES_REVIEW,
    reviewed_by: Optional[str] = None,
) -> CanonicalWorkflowSpec:
    """Builds the canonical workflow specification representing the 5-step E2E routine."""
    wid = workflow_id or f"wf-e2e-phase16-{uuid.uuid4().hex[:8]}"

    step_1_risk = StepRisk(
        step_id="can-step-1",
        application="Gmail",
        action="search_email",
        risk_level=RiskLevel.LOW,
        risk_category=RiskCategory.READ_ONLY,
        reason="Read-only search of mailbox for customer email",
        requires_confirmation=False,
    )
    step_2_risk = StepRisk(
        step_id="can-step-2",
        application="Gmail",
        action="download_attachment",
        risk_level=RiskLevel.MEDIUM,
        risk_category=RiskCategory.LOCAL_CHANGE,
        reason="Download email attachment into isolated sandbox folder",
        requires_confirmation=False,
    )
    step_3_risk = StepRisk(
        step_id="can-step-3",
        application="CRM",
        action="find_customer",
        risk_level=RiskLevel.LOW,
        risk_category=RiskCategory.READ_ONLY,
        reason="Read-only query of customer record in CRM database",
        requires_confirmation=False,
    )
    step_4_risk = StepRisk(
        step_id="can-step-4",
        application="CRM",
        action="update_customer_record",
        risk_level=RiskLevel.HIGH,
        risk_category=RiskCategory.EXTERNAL_CHANGE,
        reason="Mutates customer record status in CRM database",
        requires_confirmation=True,
    )
    step_5_risk = StepRisk(
        step_id="can-step-5",
        application="Slack",
        action="send_notification",
        risk_level=RiskLevel.MEDIUM,
        risk_category=RiskCategory.COMMUNICATION,
        reason="Broadcasts status update to operations Slack channel",
        requires_confirmation=False,
    )

    steps = [
        CanonicalStep(
            canonical_step_id="can-step-1",
            source_semantic_step_id="sem-step-1",
            source_dna_step_key="gmail:search_email",
            application="Gmail",
            event_type="WINDOW_FOCUSED",
            action="search_email",
            description="Search mailbox for incoming customer replacement request",
            input_variables=["search_query"],
            output_variables=["message_id"],
            evidence_reference="Observed in 100% of customer support sessions",
            risk=step_1_risk,
            occurrence_ratio=1.0,
            classification="invariant",
        ),
        CanonicalStep(
            canonical_step_id="can-step-2",
            source_semantic_step_id="sem-step-2",
            source_dna_step_key="file:download_attachment",
            application="Gmail",
            event_type="FILE_DOWNLOADED",
            action="download_attachment",
            description="Download customer replacement document into controlled sandbox",
            input_variables=["message_id", "attachment_filename"],
            output_variables=["downloaded_file"],
            evidence_reference="Observed attachment download across 100% of routine runs",
            risk=step_2_risk,
            occurrence_ratio=1.0,
            classification="invariant",
        ),
        CanonicalStep(
            canonical_step_id="can-step-3",
            source_semantic_step_id="sem-step-3",
            source_dna_step_key="crm:find_customer",
            application="CRM",
            event_type="WINDOW_FOCUSED",
            action="find_customer",
            description="Query CRM for customer record using email or customer identifier",
            input_variables=["customer_query"],
            output_variables=["customer_id", "customer_name"],
            evidence_reference="Observed CRM window navigation and customer lookup",
            risk=step_3_risk,
            occurrence_ratio=1.0,
            classification="invariant",
        ),
        CanonicalStep(
            canonical_step_id="can-step-4",
            source_semantic_step_id="sem-step-4",
            source_dna_step_key="crm:update_customer_record",
            application="CRM",
            event_type="WINDOW_FOCUSED",
            action="update_customer_record",
            description="Update CRM customer status to replacement_processed",
            input_variables=["customer_id", "customer_status"],
            output_variables=["crm_updated"],
            evidence_reference="Observed customer record update in CRM",
            risk=step_4_risk,
            occurrence_ratio=1.0,
            classification="invariant",
        ),
        CanonicalStep(
            canonical_step_id="can-step-5",
            source_semantic_step_id="sem-step-5",
            source_dna_step_key="slack:send_notification",
            application="Slack",
            event_type="WINDOW_FOCUSED",
            action="send_notification",
            description="Notify operations channel with verified customer update details",
            input_variables=["customer_id", "customer_name"],
            output_variables=["slack_ts"],
            evidence_reference="Observed team channel notification in Slack",
            risk=step_5_risk,
            occurrence_ratio=1.0,
            classification="invariant",
        ),
    ]

    variables = [
        ParameterBinding(
            source_parameter="search_query",
            semantic_name="search_query",
            source_field="metadata.search_query",
            associated_step_key="gmail:search_email",
            associated_application="Gmail",
            inferred_type=VariableType.STRING,
            observed_values=["has:attachment"],
            confidence=1.0,
        ),
        ParameterBinding(
            source_parameter="attachment_filename",
            semantic_name="attachment_filename",
            source_field="metadata.filename",
            associated_step_key="file:download_attachment",
            associated_application="Gmail",
            inferred_type=VariableType.FILENAME,
            observed_values=["invoice_101.pdf"],
            confidence=1.0,
        ),
        ParameterBinding(
            source_parameter="customer_query",
            semantic_name="customer_query",
            source_field="metadata.customer_id",
            associated_step_key="crm:find_customer",
            associated_application="CRM",
            inferred_type=VariableType.IDENTIFIER,
            observed_values=["cust-001"],
            confidence=1.0,
        ),
        ParameterBinding(
            source_parameter="customer_status",
            semantic_name="customer_status",
            source_field="metadata.status",
            associated_step_key="crm:update_customer_record",
            associated_application="CRM",
            inferred_type=VariableType.STRING,
            observed_values=["replacement_processed"],
            confidence=1.0,
        ),
    ]

    risk_assessment = RiskAssessment(
        overall_risk_level=RiskLevel.HIGH,
        primary_risk_category=RiskCategory.EXTERNAL_CHANGE,
        requires_human_confirmation=True,
        step_risks=[step_1_risk, step_2_risk, step_3_risk, step_4_risk, step_5_risk],
        summary="High-risk multi-application routine modifying external CRM records and dispatching Slack notifications.",
        sensitive_factors_detected=["CRM customer update", "Slack broadcast"],
    )

    approval_meta = ApprovalMetadata(
        state=approval_state,
        reviewed_by=reviewed_by,
        reviewed_at=datetime.now(timezone.utc).isoformat() if approval_state == ApprovalState.APPROVED else None,
        comments="Phase 16 Full End-to-End Governance Gate",
    )

    boundaries = WorkflowBoundaries(
        first_step="gmail:search_email",
        last_step="slack:send_notification",
        min_duration_seconds=15.0,
        max_duration_seconds=300.0,
        average_duration_seconds=45.0,
        total_supporting_sessions=5,
    )

    evidence = DNAEvidence(
        supporting_session_count=5,
        invariant_evidence="Observed invariant sequence across all 5 customer support sessions.",
        variable_evidence="Extracted customer identifier, message id, and status parameters.",
        optional_step_evidence="No optional branching observed in standard path.",
        ordering_evidence="Consistent precedence order: Gmail -> Attachment -> CRM -> Slack.",
        boundary_evidence="Sessions consistently start at email search and terminate at Slack notification.",
    )

    return CanonicalWorkflowSpec(
        workflow_id=wid,
        source_dna_id=f"dna-{wid}",
        source_semantic_workflow_id=f"sem-{wid}",
        title="Customer Replacement Request Processing",
        intent="Process customer replacement request from Gmail through CRM update and Slack notification.",
        description="End-to-end customer support routine composed of Gmail search, attachment download, CRM customer lookup, CRM update, and Slack notification.",
        version="1.0.0",
        status="specification_ready",
        steps=steps,
        optional_steps=[],
        variables=variables,
        preconditions=[
            "Gmail search API is configured and authenticated",
            "WorkFlowOS Demo CRM REST API is available and running",
            "Slack Web API bot token and channel ID are configured",
        ],
        boundaries=boundaries,
        evidence=evidence,
        risk_assessment=risk_assessment,
        approval_state=approval_meta,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


class Phase16Orchestrator:
    """Orchestrates Phase 16 Full End-to-End execution, verification, and learning."""

    def __init__(
        self,
        canonical_repo: Optional[CanonicalWorkflowRepository] = None,
        plan_repo: Optional[ExecutionPlanRepository] = None,
        exec_repo: Optional[ExecutionRepository] = None,
        verif_repo: Optional[VerificationRepository] = None,
        learning_repo: Optional[LearningRepository] = None,
        engine: Optional[ExecutionEngine] = None,
        planner: Optional[ExecutionPlanner] = None,
        verification_engine: Optional[VerificationEngine] = None,
        learning_engine: Optional[LearningEngine] = None,
    ) -> None:
        self.canonical_repo = canonical_repo or CanonicalWorkflowRepository()
        self.plan_repo = plan_repo or ExecutionPlanRepository()
        self.exec_repo = exec_repo or ExecutionRepository()
        self.verif_repo = verif_repo or VerificationRepository()
        self.learning_repo = learning_repo or LearningRepository()

        self.planner = planner or ExecutionPlanner()
        self.engine = engine or ExecutionEngine(
            canonical_repo=self.canonical_repo,
            plan_repo=self.plan_repo,
            exec_repo=self.exec_repo,
        )
        self.verification_engine = verification_engine or VerificationEngine(
            exec_repo=self.exec_repo,
            plan_repo=self.plan_repo,
            verif_repo=self.verif_repo,
        )
        self.learning_engine = learning_engine or LearningEngine(
            execution_repo=self.exec_repo,
            verification_repo=self.verif_repo,
            learning_repo=self.learning_repo,
        )

    def prepare_workflow(self, auto_approve: bool = False, reviewer: str = "Lead Reviewer") -> CanonicalWorkflowSpec:
        """Creates and saves the Phase 16 CanonicalWorkflowSpec into the repository."""
        state = ApprovalState.APPROVED if auto_approve else ApprovalState.REQUIRES_REVIEW
        spec = build_phase16_canonical_spec(approval_state=state, reviewed_by=reviewer if auto_approve else None)
        self.canonical_repo.save(spec)
        return spec

    def approve_workflow(self, workflow_id: str, reviewer: str = "Security Operator") -> CanonicalWorkflowSpec:
        """Approves a pending CanonicalWorkflowSpec."""
        spec = self.canonical_repo.get_by_id(workflow_id)
        if not spec:
            raise ValueError(f"Workflow '{workflow_id}' not found.")
        spec.approval_state = ApprovalMetadata(
            state=ApprovalState.APPROVED,
            reviewed_by=reviewer,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            comments="Approved for Phase 16 live orchestration.",
        )
        self.canonical_repo.save(spec)
        return spec

    def create_plan(
        self,
        workflow_id: str,
        runtime_inputs: Optional[Dict[str, str]] = None,
    ) -> ExecutionPlan:
        """Creates an ExecutionPlan from the approved specification."""
        spec = self.canonical_repo.get_by_id(workflow_id)
        if not spec:
            raise ValueError(f"Workflow '{workflow_id}' not found.")
        plan = self.planner.create_execution_plan(spec, runtime_inputs=runtime_inputs)
        self.plan_repo.save(plan)
        return plan

    def run_dry_run(self, execution_plan_id: str) -> ExecutionAuditRecord:
        """Executes the plan in DRY_RUN mode, guaranteeing 0 mutations and 0 real API calls."""
        return self.engine.execute_plan(
            execution_plan_id=execution_plan_id,
            execution_mode=ExecutionMode.DRY_RUN,
        )

    def execute_live(
        self,
        execution_plan_id: str,
        idempotency_key: Optional[str] = None,
        custom_sandbox_dir: Optional[str] = None,
    ) -> ExecutionAuditRecord:
        """Executes the plan in LIVE mode using real executors."""
        return self.engine.execute_plan(
            execution_plan_id=execution_plan_id,
            execution_mode=ExecutionMode.LIVE,
            idempotency_key=idempotency_key,
            custom_sandbox_dir=custom_sandbox_dir,
        )

    def verify_execution(self, execution_id: str) -> VerificationResult:
        """Independently verifies execution outcomes across Gmail, FileSystem, CRM, and Slack."""
        return self.verification_engine.verify_execution(execution_id=execution_id)

    def learn_from_execution(self, workflow_id: str) -> WorkflowReliabilityProfile:
        """Feeds execution and verification outcomes into the deterministic learning engine."""
        return self.learning_engine.analyze_workflow(workflow_id=workflow_id, persist=True)
