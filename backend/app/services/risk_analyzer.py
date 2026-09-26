"""Risk Analysis Engine (Phase 6).

Provides deterministic, explainable risk assessment for workflow steps and entire
workflows. Categorizes actions into:
- read_only: Passive observations, window focuses, querying information
- local_change: File downloads, saving files to local disk
- external_change: Mutating records in external CRM, database, or enterprise systems
- communication: Sending Slack messages, outbound emails, channel announcements
- potentially_sensitive: Involves credentials, tokens, personal identifiers, or sensitive records

STRICT PRINCIPLE:
This is an explainable decision-support model to determine human confirmation needs,
NOT a cryptographic security guarantee. Actions are classified only, NEVER executed.
"""

from typing import List, Tuple
from app.models.canonical import (
    RiskAssessment,
    RiskCategory,
    RiskLevel,
    StepRisk,
)
from app.models.semantic import SemanticStep

SENSITIVE_KEYWORDS = {
    "password", "secret", "token", "credential", "auth", "api_key",
    "ssn", "credit_card", "bank", "confidential", "private_key"
}

EXTERNAL_MUTATION_KEYWORDS = {
    "update", "modify", "save", "delete", "create", "insert",
    "post", "submit", "change", "write", "patch"
}

COMMUNICATION_KEYWORDS = {
    "slack", "teams", "notify", "message", "send", "email",
    "alert", "broadcast", "post", "chat", "whatsapp"
}


class RiskAnalyzer:
    """Performs deterministic risk analysis on workflow steps and aggregates overall risk."""

    def analyze_step(
        self,
        step_id: str,
        application: str,
        action: str,
        description: str,
        event_type: str = "",
    ) -> StepRisk:
        """Classify a single workflow step into a RiskCategory and RiskLevel with an explainable reason."""
        app_lower = application.lower()
        action_lower = action.lower()
        desc_lower = description.lower()
        combined_text = f"{app_lower} {action_lower} {desc_lower} {event_type.lower()}"

        # 1. Check for potentially sensitive data
        for kw in SENSITIVE_KEYWORDS:
            if kw in combined_text:
                return StepRisk(
                    step_id=step_id,
                    application=application,
                    action=action,
                    risk_level=RiskLevel.HIGH,
                    risk_category=RiskCategory.POTENTIALLY_SENSITIVE,
                    reason=f"Step references sensitive keyword '{kw}' requiring strict privacy handling.",
                    requires_confirmation=True,
                )

        # 2. External system mutations (CRM, Database, Enterprise systems)
        if any(crm_kw in app_lower for crm_kw in ["crm", "salesforce", "hubspot", "database"]):
            if any(mut_kw in combined_text for mut_kw in EXTERNAL_MUTATION_KEYWORDS):
                return StepRisk(
                    step_id=step_id,
                    application=application,
                    action=action,
                    risk_level=RiskLevel.HIGH,
                    risk_category=RiskCategory.EXTERNAL_CHANGE,
                    reason=f"Step mutates customer or enterprise records in external {application} system.",
                    requires_confirmation=True,
                )
            # Default CRM observation
            return StepRisk(
                step_id=step_id,
                application=application,
                action=action,
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason=f"Step inspects or focuses {application} records without modifying external data.",
                requires_confirmation=False,
            )

        # 3. Communication channels (Slack, Teams, Email, WhatsApp)
        if any(comm_app in app_lower for comm_app in ["slack", "teams", "whatsapp", "chat"]):
            return StepRisk(
                step_id=step_id,
                application=application,
                action=action,
                risk_level=RiskLevel.MEDIUM,
                risk_category=RiskCategory.COMMUNICATION,
                reason=f"Step sends outbound notification or team announcement in {application}.",
                requires_confirmation=True,
            )

        if "gmail" in app_lower or "email" in app_lower or "outlook" in app_lower:
            if any(send_kw in combined_text for send_kw in ["send", "reply", "compose", "forward"]):
                return StepRisk(
                    step_id=step_id,
                    application=application,
                    action=action,
                    risk_level=RiskLevel.MEDIUM,
                    risk_category=RiskCategory.COMMUNICATION,
                    reason=f"Step sends outbound email communication via {application}.",
                    requires_confirmation=True,
                )
            # Read-only email checking
            return StepRisk(
                step_id=step_id,
                application=application,
                action=action,
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason=f"Step reviews incoming message or focuses window in {application} (read-only observation).",
                requires_confirmation=False,
            )

        # 4. Local filesystem modifications (Downloads, file writes)
        if any(fs_kw in app_lower or fs_kw in event_type.lower() for fs_kw in ["file system", "download", "disk", "folder"]):
            return StepRisk(
                step_id=step_id,
                application=application,
                action=action,
                risk_level=RiskLevel.MEDIUM,
                risk_category=RiskCategory.LOCAL_CHANGE,
                reason=f"Step modifies local filesystem by downloading or saving files via {application}.",
                requires_confirmation=False,
            )

        # 5. Default window focus or observation
        if "focus" in combined_text or "view" in combined_text or "window" in combined_text:
            return StepRisk(
                step_id=step_id,
                application=application,
                action=action,
                risk_level=RiskLevel.LOW,
                risk_category=RiskCategory.READ_ONLY,
                reason=f"Step focuses or observes {application} interface without side-effects.",
                requires_confirmation=False,
            )

        # Fallback
        return StepRisk(
            step_id=step_id,
            application=application,
            action=action,
            risk_level=RiskLevel.LOW,
            risk_category=RiskCategory.READ_ONLY,
            reason=f"Standard activity in {application} with no external modifications detected.",
            requires_confirmation=False,
        )

    def assess_workflow_risks(
        self,
        steps: List[Tuple[str, str, str, str, str]],  # (step_id, app, action, desc, event_type)
    ) -> RiskAssessment:
        """Analyze a list of steps and produce an aggregated workflow-level RiskAssessment."""
        step_risks: List[StepRisk] = []
        sensitive_factors: List[str] = []

        has_high = False
        has_medium = False
        category_counts = {
            RiskCategory.READ_ONLY: 0,
            RiskCategory.LOCAL_CHANGE: 0,
            RiskCategory.EXTERNAL_CHANGE: 0,
            RiskCategory.COMMUNICATION: 0,
            RiskCategory.POTENTIALLY_SENSITIVE: 0,
        }

        for s_id, app, action, desc, ev_type in steps:
            sr = self.analyze_step(s_id, app, action, desc, ev_type)
            step_risks.append(sr)
            category_counts[sr.risk_category] += 1

            if sr.risk_level == RiskLevel.HIGH:
                has_high = True
            elif sr.risk_level == RiskLevel.MEDIUM:
                has_medium = True

            if sr.risk_category == RiskCategory.POTENTIALLY_SENSITIVE:
                sensitive_factors.append(f"{sr.step_id}: {sr.reason}")
            elif sr.risk_category == RiskCategory.EXTERNAL_CHANGE:
                sensitive_factors.append(f"{sr.step_id}: External mutation in {sr.application}")

        # Overall risk level
        if has_high:
            overall_level = RiskLevel.HIGH
        elif has_medium:
            overall_level = RiskLevel.MEDIUM
        else:
            overall_level = RiskLevel.LOW

        # Primary risk category (highest impact category present)
        if category_counts[RiskCategory.POTENTIALLY_SENSITIVE] > 0:
            primary_cat = RiskCategory.POTENTIALLY_SENSITIVE
        elif category_counts[RiskCategory.EXTERNAL_CHANGE] > 0:
            primary_cat = RiskCategory.EXTERNAL_CHANGE
        elif category_counts[RiskCategory.COMMUNICATION] > 0:
            primary_cat = RiskCategory.COMMUNICATION
        elif category_counts[RiskCategory.LOCAL_CHANGE] > 0:
            primary_cat = RiskCategory.LOCAL_CHANGE
        else:
            primary_cat = RiskCategory.READ_ONLY

        # Human confirmation requirement: always required if any step modifies external state, sends communication, or touches sensitive data
        requires_confirmation = (
            category_counts[RiskCategory.EXTERNAL_CHANGE] > 0
            or category_counts[RiskCategory.COMMUNICATION] > 0
            or category_counts[RiskCategory.POTENTIALLY_SENSITIVE] > 0
            or category_counts[RiskCategory.LOCAL_CHANGE] > 0
        )

        # Explainable summary
        summary_parts = []
        if category_counts[RiskCategory.EXTERNAL_CHANGE] > 0:
            summary_parts.append(f"{category_counts[RiskCategory.EXTERNAL_CHANGE]} step(s) perform external record changes")
        if category_counts[RiskCategory.COMMUNICATION] > 0:
            summary_parts.append(f"{category_counts[RiskCategory.COMMUNICATION]} step(s) broadcast team communications")
        if category_counts[RiskCategory.LOCAL_CHANGE] > 0:
            summary_parts.append(f"{category_counts[RiskCategory.LOCAL_CHANGE]} step(s) alter local files")
        if category_counts[RiskCategory.READ_ONLY] > 0:
            summary_parts.append(f"{category_counts[RiskCategory.READ_ONLY]} read-only observation step(s)")

        summary = f"Workflow contains {', '.join(summary_parts)}."
        if requires_confirmation:
            summary += " Explicit human approval is recommended prior to any future automated execution."

        return RiskAssessment(
            overall_risk_level=overall_level,
            primary_risk_category=primary_cat,
            requires_human_confirmation=requires_confirmation,
            step_risks=step_risks,
            summary=summary,
            sensitive_factors_detected=sensitive_factors,
        )
