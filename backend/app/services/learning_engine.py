"""Workflow Learning & Reliability Intelligence Engine (Phase 11).

Analyzes historical execution and post-execution verification audits to deterministically:
1. Calculate workflow-level and step-level reliability metrics.
2. Classify failures into standardized categories (EXECUTION_FAILURE, VERIFICATION_FAILURE, POLICY_BLOCK, UNSUPPORTED_STRATEGY, PARAMETER_PROBLEM).
3. Detect repeated operational patterns without LLM hallucinations.
4. Generate evidence-backed advisory improvement suggestions.
5. Persist learning audit events and reliability profiles in SQLite.

STRICT SAFETY GUARANTEES:
- Learning is strictly read/aggregate/analyze only.
- NEVER automatically modifies CanonicalWorkflowSpec.
- NEVER modifies approval state or risk classification.
- NEVER automatically triggers workflow execution.
- NEVER calls external APIs (Slack, Gmail, CRM).
- 100% deterministic numeric and rule-based calculations without LLM dependency.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.models.canonical import CanonicalWorkflowSpec
from app.models.execution import (
    ExecutionAuditRecord,
    ExecutionOverallStatus,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.learning import (
    DetectedPattern,
    FailureCategory,
    ImprovementSuggestion,
    LearningEventType,
    LearningThresholds,
    StepReliability,
    WorkflowLearningEvent,
    WorkflowReliabilityProfile,
)
from app.models.verification import VerificationResult, VerificationStatus
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository


class LearningEngine:
    """Deterministic Learning & Reliability Intelligence Engine."""

    def __init__(
        self,
        execution_repo: ExecutionRepository,
        verification_repo: VerificationRepository,
        learning_repo: LearningRepository,
        canonical_repo: Optional[Any] = None,
        thresholds: Optional[LearningThresholds] = None,
    ) -> None:
        self.execution_repo = execution_repo
        self.verification_repo = verification_repo
        self.learning_repo = learning_repo
        self.canonical_repo = canonical_repo
        self.thresholds = thresholds or LearningThresholds()

    def classify_failure(
        self,
        step_result: Optional[ExecutionStepResult],
        overall_status: ExecutionOverallStatus,
        verification_status: Optional[VerificationStatus],
    ) -> FailureCategory:
        """Deterministically classifies an execution outcome into standardized FailureCategory."""
        # 1. Verification Failure takes precedence over executor success
        if (
            overall_status == ExecutionOverallStatus.COMPLETED
            and verification_status == VerificationStatus.FAILED
        ):
            return FailureCategory.VERIFICATION_FAILURE

        if step_result:
            if step_result.status == ExecutionStepStatus.BLOCKED:
                blocked_reason = (step_result.blocked_reason or "").upper()
                error_msg = (step_result.error or "").upper()

                if "UNSUPPORTED_EXECUTION_STRATEGY" in blocked_reason or "UNSUPPORTED" in blocked_reason:
                    return FailureCategory.UNSUPPORTED_STRATEGY
                if "PARAMETER" in blocked_reason or "UNRESOLVED" in blocked_reason or "PARAMETER" in error_msg:
                    return FailureCategory.PARAMETER_PROBLEM
                return FailureCategory.POLICY_BLOCK

            if step_result.status == ExecutionStepStatus.FAILED:
                return FailureCategory.EXECUTION_FAILURE

        if overall_status == ExecutionOverallStatus.BLOCKED:
            return FailureCategory.POLICY_BLOCK

        if overall_status == ExecutionOverallStatus.FAILED:
            return FailureCategory.EXECUTION_FAILURE

        return FailureCategory.UNKNOWN_OUTCOME

    def analyze_workflow(
        self,
        workflow_id: str,
        persist: bool = True,
    ) -> WorkflowReliabilityProfile:
        """Aggregates execution and verification history into a deterministic WorkflowReliabilityProfile."""
        # 1. Fetch historical executions for this workflow
        executions = self.execution_repo.list_all(workflow_id=workflow_id, limit=200)

        # If no executions recorded yet, return an empty, valid profile
        if not executions:
            empty_profile = WorkflowReliabilityProfile(
                workflow_id=workflow_id,
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                blocked_executions=0,
                verified_executions=0,
                verification_failures=0,
                unknown_verifications=0,
                execution_success_rate=0.0,
                verification_rate=0.0,
                blocked_rate=0.0,
                reliability_rate=0.0,
                step_reliabilities=[],
                detected_patterns=[],
                suggestions=[],
                latest_events=[],
                computed_at=datetime.now(timezone.utc).isoformat(),
            )
            if persist:
                self.learning_repo.save_profile(empty_profile)
            return empty_profile

        # Sort chronologically for deterministic event order
        sorted_executions = sorted(executions, key=lambda x: x.start_time)

        # 2. Correlate with verification results
        execution_verifications: Dict[str, Optional[VerificationResult]] = {}
        for ex in sorted_executions:
            v_res = self.verification_repo.get_latest_by_execution_id(ex.execution_id)
            if not v_res and ex.verification_id:
                v_res = self.verification_repo.get_by_id(ex.verification_id)
            execution_verifications[ex.execution_id] = v_res

        # 3. Aggregate workflow-level counts
        total_executions = len(sorted_executions)
        successful_executions = 0
        failed_executions = 0
        blocked_executions = 0
        verified_executions = 0
        verification_failures = 0
        unknown_verifications = 0

        last_execution_at: Optional[str] = sorted_executions[-1].start_time
        last_success_at: Optional[str] = None
        last_failure_at: Optional[str] = None

        events: List[WorkflowLearningEvent] = []

        # Step aggregation tracking dictionaries: step_id -> stats
        step_stats: Dict[str, Dict[str, Any]] = {}

        for ex in sorted_executions:
            v_res = execution_verifications.get(ex.execution_id)
            v_status = v_res.overall_status if v_res else None

            # Process step outcomes
            for step_res in ex.step_results:
                step_id = step_res.planned_step_id or step_res.action_name
                if step_id not in step_stats:
                    step_stats[step_id] = {
                        "planned_step_id": step_id,
                        "action": step_res.action_name,
                        "target": step_res.target_application,
                        "selected_strategy": step_res.selected_strategy,
                        "total_executions": 0,
                        "successful_executions": 0,
                        "failed_executions": 0,
                        "blocked_executions": 0,
                        "verified_success_count": 0,
                        "verification_failure_count": 0,
                        "last_outcome": "UNKNOWN",
                        "blocked_reasons": [],
                        "execution_ids": [],
                        "verification_ids": [],
                    }

                st = step_stats[step_id]
                st["total_executions"] += 1
                st["execution_ids"].append(ex.execution_id)
                if step_res.selected_strategy:
                    st["selected_strategy"] = step_res.selected_strategy

                # Correlate step verification checks
                step_v_check = None
                if v_res:
                    for chk in v_res.checks:
                        if (
                            chk.planned_step_id == step_res.planned_step_id
                            or chk.execution_step_id == step_res.execution_step_id
                        ):
                            step_v_check = chk
                            break

                if step_res.status == ExecutionStepStatus.SUCCESS:
                    st["successful_executions"] += 1
                    if step_v_check and step_v_check.status == VerificationStatus.VERIFIED:
                        st["verified_success_count"] += 1
                        st["last_outcome"] = "VERIFIED"
                    elif step_v_check and step_v_check.status == VerificationStatus.FAILED:
                        st["verification_failure_count"] += 1
                        st["last_outcome"] = "VERIFICATION_FAILED"
                    else:
                        st["last_outcome"] = "SUCCESS"

                elif step_res.status == ExecutionStepStatus.FAILED:
                    st["failed_executions"] += 1
                    st["last_outcome"] = "FAILED"

                elif step_res.status == ExecutionStepStatus.BLOCKED:
                    st["blocked_executions"] += 1
                    st["last_outcome"] = "BLOCKED"
                    if step_res.blocked_reason:
                        st["blocked_reasons"].append(step_res.blocked_reason)

                if v_res:
                    st["verification_ids"].append(v_res.verification_run_id)

            # Execution status aggregation
            if ex.status == ExecutionOverallStatus.COMPLETED:
                successful_executions += 1
                if v_status == VerificationStatus.VERIFIED:
                    verified_executions += 1
                    last_success_at = ex.start_time
                    events.append(
                        WorkflowLearningEvent(
                            workflow_id=workflow_id,
                            timestamp=ex.start_time,
                            event_type=LearningEventType.EXECUTION_SUCCESS_OBSERVED,
                            execution_id=ex.execution_id,
                            verification_id=v_res.verification_run_id if v_res else None,
                            observed_evidence={
                                "execution_status": ex.status.value,
                                "verification_status": v_status.value if v_status else None,
                                "verified_checks": v_res.verified_count if v_res else 0,
                            },
                            insight=f"Execution '{ex.execution_id}' succeeded and all expected state changes were empirically verified.",
                            confidence=1.0,
                        )
                    )
                elif v_status == VerificationStatus.FAILED:
                    verification_failures += 1
                    last_failure_at = ex.start_time
                    events.append(
                        WorkflowLearningEvent(
                            workflow_id=workflow_id,
                            timestamp=ex.start_time,
                            event_type=LearningEventType.VERIFICATION_FAILURE_OBSERVED,
                            execution_id=ex.execution_id,
                            verification_id=v_res.verification_run_id if v_res else None,
                            observed_evidence={
                                "execution_status": ex.status.value,
                                "verification_status": v_status.value if v_status else None,
                                "failed_checks": v_res.failed_count if v_res else 0,
                            },
                            insight=f"Execution '{ex.execution_id}' reported executor success, but post-execution verification detected state mismatch.",
                            confidence=1.0,
                        )
                    )
                else:
                    unknown_verifications += 1

            elif ex.status == ExecutionOverallStatus.FAILED:
                failed_executions += 1
                last_failure_at = ex.start_time
                events.append(
                    WorkflowLearningEvent(
                        workflow_id=workflow_id,
                        timestamp=ex.start_time,
                        event_type=LearningEventType.EXECUTION_FAILURE_OBSERVED,
                        execution_id=ex.execution_id,
                        observed_evidence={"error_summary": ex.error_summary},
                        insight=f"Execution '{ex.execution_id}' failed with error: {ex.error_summary or 'executor exception'}.",
                        confidence=1.0,
                    )
                )

            elif ex.status == ExecutionOverallStatus.BLOCKED:
                blocked_executions += 1
                last_failure_at = ex.start_time

                # Check if it was an unsupported strategy block or parameter issue
                unsupported_strategy_found = any(
                    (s.blocked_reason or "") == "UNSUPPORTED_EXECUTION_STRATEGY" for s in ex.step_results
                )
                parameter_issue_found = any(
                    "PARAMETER" in (s.blocked_reason or "").upper() for s in ex.step_results
                )

                if unsupported_strategy_found:
                    events.append(
                        WorkflowLearningEvent(
                            workflow_id=workflow_id,
                            timestamp=ex.start_time,
                            event_type=LearningEventType.STRATEGY_BLOCK_OBSERVED,
                            execution_id=ex.execution_id,
                            observed_evidence={
                                "blocked_code": "UNSUPPORTED_EXECUTION_STRATEGY",
                                "steps_blocked": [
                                    s.action_name for s in ex.step_results if s.status == ExecutionStepStatus.BLOCKED
                                ],
                            },
                            insight=f"Execution '{ex.execution_id}' was safely blocked: unsupported execution strategy (required strategy is architecturally represented but NOT implemented).",
                            confidence=1.0,
                        )
                    )
                elif parameter_issue_found:
                    events.append(
                        WorkflowLearningEvent(
                            workflow_id=workflow_id,
                            timestamp=ex.start_time,
                            event_type=LearningEventType.PARAMETER_PROBLEM_OBSERVED,
                            execution_id=ex.execution_id,
                            observed_evidence={"error": ex.error_summary},
                            insight=f"Execution '{ex.execution_id}' was blocked due to unresolved required parameters.",
                            confidence=1.0,
                        )
                    )
                else:
                    events.append(
                        WorkflowLearningEvent(
                            workflow_id=workflow_id,
                            timestamp=ex.start_time,
                            event_type=LearningEventType.STRATEGY_BLOCK_OBSERVED,
                            execution_id=ex.execution_id,
                            observed_evidence={"error": ex.error_summary},
                            insight=f"Execution '{ex.execution_id}' was blocked by policy: {ex.error_summary or 'Execution policy restriction'}.",
                            confidence=1.0,
                        )
                    )

        # 4. Deterministic Reliability Calculations
        completed_executable_executions = verified_executions + failed_executions + verification_failures
        total_executable = successful_executions + failed_executions

        execution_success_rate = (
            round(successful_executions / total_executable, 4) if total_executable > 0 else 0.0
        )
        verification_rate = (
            round(verified_executions / successful_executions, 4) if successful_executions > 0 else 0.0
        )
        blocked_rate = (
            round(blocked_executions / total_executions, 4) if total_executions > 0 else 0.0
        )
        reliability_rate = (
            round(verified_executions / completed_executable_executions, 4)
            if completed_executable_executions > 0
            else 0.0
        )

        # 5. Build StepReliability items & Detect Patterns
        step_reliabilities: List[StepReliability] = []
        detected_patterns: List[DetectedPattern] = []
        suggestions: List[ImprovementSuggestion] = []

        for step_id, st in step_stats.items():
            pattern_name = None

            # Pattern A: Repeated Verification Failures
            if st["verification_failure_count"] >= self.thresholds.repeated_failure_threshold:
                pattern_name = "REPEATED_VERIFICATION_FAILURE"
                pat_desc = f"Step '{st['action']}' has experienced {st['verification_failure_count']} repeated post-execution verification failures."
                detected_patterns.append(
                    DetectedPattern(
                        pattern_type="REPEATED_VERIFICATION_FAILURE",
                        description=pat_desc,
                        affected_step_id=st["planned_step_id"],
                        affected_action=st["action"],
                        occurrence_count=st["verification_failure_count"],
                        evidence_execution_ids=st["execution_ids"][-5:],
                        evidence_verification_ids=st["verification_ids"][-5:],
                    )
                )
                suggestions.append(
                    ImprovementSuggestion(
                        workflow_id=workflow_id,
                        affected_step_id=st["planned_step_id"],
                        affected_step_action=st["action"],
                        category="VERIFICATION_DEFINITION",
                        title="Review Expected-State Definition",
                        suggestion=f"Review the expected-state criteria for Step '{st['action']}' on target '{st['target']}'. The executor reports success but verified state checks consistently fail.",
                        evidence={
                            "verification_failures": st["verification_failure_count"],
                            "affected_step_id": st["planned_step_id"],
                            "execution_ids": st["execution_ids"][-5:],
                            "verification_ids": st["verification_ids"][-5:],
                        },
                        is_advisory=True,
                    )
                )

            # Pattern B: Repeated Unsupported Strategy
            unsupported_count = sum(
                1 for r in st["blocked_reasons"] if "UNSUPPORTED_EXECUTION_STRATEGY" in r or "UNSUPPORTED" in r
            )
            if (
                st["blocked_executions"] >= self.thresholds.repeated_block_threshold
                and (unsupported_count >= self.thresholds.repeated_block_threshold or st["selected_strategy"] in [None, "NONE"])
            ):
                pattern_name = "REPEATED_UNSUPPORTED_STRATEGY"
                pat_desc = f"Step '{st['action']}' has been blocked {st['blocked_executions']} times because no implemented executor supports its required strategy."
                detected_patterns.append(
                    DetectedPattern(
                        pattern_type="REPEATED_UNSUPPORTED_STRATEGY",
                        description=pat_desc,
                        affected_step_id=st["planned_step_id"],
                        affected_action=st["action"],
                        occurrence_count=st["blocked_executions"],
                        evidence_execution_ids=st["execution_ids"][-5:],
                    )
                )
                suggestions.append(
                    ImprovementSuggestion(
                        workflow_id=workflow_id,
                        affected_step_id=st["planned_step_id"],
                        affected_step_action=st["action"],
                        category="STRATEGY_REQUIREMENT",
                        title="Implement Required Execution Strategy",
                        suggestion=f"An implemented execution strategy for Step '{st['action']}' on '{st['target']}' is required before this workflow can execute without blocking.",
                        evidence={
                            "blocked_count": st["blocked_executions"],
                            "affected_step_id": st["planned_step_id"],
                            "execution_ids": st["execution_ids"][-5:],
                            "action": st["action"],
                            "target": st["target"],
                        },
                        is_advisory=True,
                    )
                )

            # Pattern C: Repeated Parameter Problems
            param_block_count = sum(
                1 for r in st["blocked_reasons"] if "PARAMETER" in r.upper() or "UNRESOLVED" in r.upper()
            )
            if param_block_count >= self.thresholds.repeated_parameter_problem_threshold:
                pattern_name = "REPEATED_PARAMETER_PROBLEM"
                pat_desc = f"Step '{st['action']}' has repeatedly experienced unresolved parameter blocks across {param_block_count} execution attempts."
                detected_patterns.append(
                    DetectedPattern(
                        pattern_type="REPEATED_PARAMETER_PROBLEM",
                        description=pat_desc,
                        affected_step_id=st["planned_step_id"],
                        affected_action=st["action"],
                        occurrence_count=param_block_count,
                        evidence_execution_ids=st["execution_ids"][-5:],
                    )
                )
                suggestions.append(
                    ImprovementSuggestion(
                        workflow_id=workflow_id,
                        affected_step_id=st["planned_step_id"],
                        affected_step_action=st["action"],
                        category="PARAMETER_CONFIG",
                        title="Provide Stable Runtime Parameters",
                        suggestion=f"Parameters for Step '{st['action']}' are frequently unresolved. Ensure required parameters are bound with static defaults or validated before execution.",
                        evidence={
                            "parameter_blocks": param_block_count,
                            "affected_step_id": st["planned_step_id"],
                            "execution_ids": st["execution_ids"][-5:],
                        },
                        is_advisory=True,
                    )
                )

            step_reliabilities.append(
                StepReliability(
                    planned_step_id=st["planned_step_id"],
                    action=st["action"],
                    target=st["target"],
                    selected_strategy=st["selected_strategy"],
                    total_executions=st["total_executions"],
                    successful_executions=st["successful_executions"],
                    failed_executions=st["failed_executions"],
                    blocked_executions=st["blocked_executions"],
                    verified_success_count=st["verified_success_count"],
                    verification_failure_count=st["verification_failure_count"],
                    last_outcome=st["last_outcome"],
                    failure_pattern=pattern_name,
                )
            )

        # Pattern D: Repeated Verified Successes (Workflow-Level Milestone)
        if (
            verified_executions >= self.thresholds.high_reliability_threshold
            and failed_executions == 0
            and verification_failures == 0
        ):
            detected_patterns.append(
                DetectedPattern(
                    pattern_type="REPEATED_VERIFIED_SUCCESS",
                    description=f"Workflow '{workflow_id}' has accumulated {verified_executions} repeated verified successful executions with zero verification failures.",
                    occurrence_count=verified_executions,
                    evidence_execution_ids=[ex.execution_id for ex in sorted_executions][-5:],
                )
            )
            suggestions.append(
                ImprovementSuggestion(
                    workflow_id=workflow_id,
                    category="HIGH_RELIABILITY",
                    title="Verified Reliability Benchmark Achieved",
                    suggestion=f"Workflow has demonstrated consistent reliability ({reliability_rate * 100:.1f}% verified rate across {verified_executions} runs). Recommended for production scheduling.",
                    evidence={
                        "verified_executions": verified_executions,
                        "reliability_rate": reliability_rate,
                        "execution_ids": [ex.execution_id for ex in sorted_executions][-5:],
                    },
                    is_advisory=True,
                )
            )

        # 6. Build the complete profile
        profile = WorkflowReliabilityProfile(
            workflow_id=workflow_id,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            blocked_executions=blocked_executions,
            verified_executions=verified_executions,
            verification_failures=verification_failures,
            unknown_verifications=unknown_verifications,
            execution_success_rate=execution_success_rate,
            verification_rate=verification_rate,
            blocked_rate=blocked_rate,
            reliability_rate=reliability_rate,
            last_execution_at=last_execution_at,
            last_success_at=last_success_at,
            last_failure_at=last_failure_at,
            step_reliabilities=step_reliabilities,
            detected_patterns=detected_patterns,
            suggestions=suggestions,
            latest_events=events[-20:],  # retain recent events
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

        # 7. Persist to SQLite
        if persist:
            self.learning_repo.save_events(events)
            self.learning_repo.save_profile(profile)

        return profile
