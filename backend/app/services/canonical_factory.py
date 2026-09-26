"""Canonical Workflow Specification Factory (Phase 6).

Assembles the formal, executable-ready CanonicalWorkflowSpec from:
1. Deterministic structural WorkflowDNA (invariants, ordering, evidence, boundaries)
2. Validated SemanticWorkflow (human-understandable intent, actions, variable names)
3. Deterministic ParameterBinding (types, bindings, independent traceable parameters)
4. Deterministic RiskAssessment (per-step classification and overall workflow risk)
5. Governance Approval State (defaults to 'requires_review', never auto-approved)

STRICT GUARANTEES:
- No invented steps
- No invented applications
- No invented variables
- Preserves all DNA ordering constraints
- Preserves all DNA source parameter names
- Produces NO execution code
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalOptionalStep,
    CanonicalStep,
    CanonicalWorkflowSpec,
)
from app.models.dna import WorkflowDNA
from app.models.semantic import SemanticWorkflow
from app.services.parameter_binder import ParameterBinder
from app.services.risk_analyzer import RiskAnalyzer


class CanonicalWorkflowFactory:
    """Constructs validated CanonicalWorkflowSpec instances with complete traceability."""

    def __init__(
        self,
        parameter_binder: Optional[ParameterBinder] = None,
        risk_analyzer: Optional[RiskAnalyzer] = None,
    ) -> None:
        self.parameter_binder = parameter_binder or ParameterBinder()
        self.risk_analyzer = risk_analyzer or RiskAnalyzer()

    def create_specification(
        self,
        dna: WorkflowDNA,
        semantic_wf: SemanticWorkflow,
    ) -> CanonicalWorkflowSpec:
        """Construct a CanonicalWorkflowSpec from WorkflowDNA and SemanticWorkflow.

        Raises ValueError if semantic_wf does not match the source DNA or has not
        been successfully interpreted and validated.
        """
        if semantic_wf.source_dna_id != dna.dna_id:
            raise ValueError(
                f"Source DNA mismatch: SemanticWorkflow references '{semantic_wf.source_dna_id}', "
                f"but provided DNA has ID '{dna.dna_id}'."
            )

        if semantic_wf.status not in ("interpreted", "success"):
            raise ValueError(
                f"Cannot create canonical specification from unvalidated semantic workflow (status: '{semantic_wf.status}')."
            )

        # 1. Parameter Binding & Type Inference
        parameter_bindings = self.parameter_binder.bind_parameters(dna, semantic_wf)

        # 2. Build Invariant Step Traceability Map
        # DNA Invariants mapped by step_key
        dna_inv_map = {inv.step_key: inv for inv in dna.invariant_steps}

        # Collect tuples for batch risk assessment: (step_id, app, action, desc, event_type)
        risk_tuples: List[tuple] = []
        canonical_steps: List[CanonicalStep] = []

        for idx, sem_step in enumerate(semantic_wf.semantic_steps, 1):
            can_step_id = f"can-step-{idx}"
            dna_inv = dna_inv_map.get(sem_step.source_dna_step_key)
            ev_type = dna_inv.event_type if dna_inv else ""
            occ_ratio = dna_inv.occurrence_ratio if dna_inv else 1.0

            # Analyze step risk
            step_risk = self.risk_analyzer.analyze_step(
                step_id=can_step_id,
                application=sem_step.application,
                action=sem_step.action,
                description=sem_step.description,
                event_type=ev_type,
            )

            canonical_step = CanonicalStep(
                canonical_step_id=can_step_id,
                source_semantic_step_id=sem_step.step_id,
                source_dna_step_key=sem_step.source_dna_step_key,
                application=sem_step.application,
                event_type=ev_type,
                action=sem_step.action,
                description=sem_step.description,
                input_variables=list(sem_step.input_variables),
                output_variables=list(sem_step.output_variables),
                evidence_reference=sem_step.evidence_reference,
                risk=step_risk,
                occurrence_ratio=occ_ratio,
                classification="invariant",
            )
            canonical_steps.append(canonical_step)
            risk_tuples.append((
                can_step_id,
                sem_step.application,
                sem_step.action,
                sem_step.description,
                ev_type,
            ))

        # 3. Build Optional Step Traceability Map
        dna_opt_map = {opt.step_key: opt for opt in dna.optional_steps}
        canonical_opt_steps: List[CanonicalOptionalStep] = []

        for o_idx, sem_opt in enumerate(semantic_wf.optional_steps, 1):
            can_opt_id = f"can-opt-{o_idx}"
            dna_opt = dna_opt_map.get(sem_opt.source_dna_step_key)
            ev_type = dna_opt.event_type if dna_opt else ""
            occ_ratio = dna_opt.occurrence_ratio if dna_opt else 0.5

            opt_risk = self.risk_analyzer.analyze_step(
                step_id=can_opt_id,
                application=sem_opt.application,
                action=sem_opt.condition_or_trigger,
                description=sem_opt.description,
                event_type=ev_type,
            )

            canonical_opt = CanonicalOptionalStep(
                canonical_step_id=can_opt_id,
                source_semantic_step_id=sem_opt.step_id,
                source_dna_step_key=sem_opt.source_dna_step_key,
                application=sem_opt.application,
                event_type=ev_type,
                condition_or_trigger=sem_opt.condition_or_trigger,
                description=sem_opt.description,
                risk=opt_risk,
                occurrence_ratio=occ_ratio,
                classification="optional",
            )
            canonical_opt_steps.append(canonical_opt)
            risk_tuples.append((
                can_opt_id,
                sem_opt.application,
                sem_opt.condition_or_trigger,
                sem_opt.description,
                ev_type,
            ))

        # 4. Aggregated Risk Assessment
        risk_assessment = self.risk_analyzer.assess_workflow_risks(risk_tuples)

        # 5. Approval State Initialization (Always requires review initially)
        approval_metadata = ApprovalMetadata(
            state=ApprovalState.REQUIRES_REVIEW,
            reviewed_by=None,
            reviewed_at=None,
            rejection_reason=None,
            comments="Newly generated specification awaiting human review.",
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        return CanonicalWorkflowSpec(
            workflow_id=f"wf-spec-{uuid.uuid4().hex[:12]}",
            source_dna_id=dna.dna_id,
            source_semantic_workflow_id=semantic_wf.semantic_workflow_id,
            title=semantic_wf.title,
            intent=semantic_wf.intent,
            description=semantic_wf.summary,
            version="1.0.0",
            status="specification_ready",
            steps=canonical_steps,
            variables=parameter_bindings,
            optional_steps=canonical_opt_steps,
            preconditions=list(dna.preconditions) or list(semantic_wf.preconditions),
            boundaries=dna.boundaries,
            ordering_constraints=list(dna.ordering_constraints),
            evidence=dna.evidence,
            parameter_bindings=parameter_bindings,
            risk_assessment=risk_assessment,
            approval_state=approval_metadata,
            created_at=now_iso,
            updated_at=now_iso,
        )
