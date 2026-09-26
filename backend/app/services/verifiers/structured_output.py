"""Structured Output Verification Strategy (Phase 9).

Deterministic post-execution verification for structured JSON artifacts:
- Parses JSON data from sandbox files
- Compares expected key-values against actual observed keys
- NO LLM involvement: 100% deterministic comparison
- Reports exact field matches, mismatches, and missing properties
- Enforces strict sandbox containment
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models.execution import ExecutionStepResult
from app.models.execution_plan import PlannedStep
from app.models.verification import (
    VerificationCheck,
    VerificationStatus,
    VerificationStrategyType,
)
from app.services.verifiers.base import BaseVerificationStrategy


class StructuredOutputVerificationStrategy(BaseVerificationStrategy):
    """Verifies structured JSON payloads inside the execution sandbox without LLM."""

    @property
    def name(self) -> str:
        return "StructuredOutputVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STRUCTURED_OUTPUT

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Supports steps with local JSON file artifacts inside sandbox."""
        if step_result.executor_name == "GmailApiExecutor" or "gmail" in step.application.lower():
            return False

        filename = (
            step.resolved_parameters.get("file_name")
            or step.resolved_parameters.get("filename")
            or ""
        )
        if filename.lower().endswith(".json"):
            return True

        for res in step_result.affected_resources:
            if res.lower().endswith(".json"):
                return True

        if step_result.output and isinstance(step_result.output, dict):
            # Only for local sandbox executions that write files
            return step_result.executor_name == "ControlledLocalExecutor"

        return False

    def _resolve_and_verify_sandbox_path(self, target_path_str: str, sandbox_root: str) -> Tuple[bool, Optional[Path], str]:
        """Strict sandbox boundary resolution with path traversal rejection."""
        try:
            sandbox_real = Path(sandbox_root).resolve()

            if ".." in target_path_str.replace("\\", "/").split("/"):
                return False, None, f"Path traversal rejected: '{target_path_str}' contains '..'"

            target_p = Path(target_path_str)
            if target_p.is_absolute():
                resolved = target_p.resolve()
            else:
                resolved = (sandbox_real / target_p).resolve()

            try:
                resolved.relative_to(sandbox_real)
            except ValueError:
                return False, None, f"Target path '{resolved}' escapes configured sandbox '{sandbox_real}'"

            return True, resolved, ""
        except Exception as e:
            return False, None, f"Path resolution error: {str(e)}"

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Builds structured output verification checks."""
        checks: List[VerificationCheck] = []

        target_name = (
            step.resolved_parameters.get("file_name")
            or step.resolved_parameters.get("filename")
        )
        if not target_name and step_result.affected_resources:
            target_name = Path(step_result.affected_resources[0]).name

        if not target_name:
            target_name = f"step_{step.plan_step_id}_output.json"

        # Determine expected fields from step parameters or custom expectations
        expected_fields: Dict[str, Any] = {}
        if custom_expectations and step.plan_step_id in custom_expectations:
            expected_fields = custom_expectations[step.plan_step_id]
        elif custom_expectations and "fields" in custom_expectations:
            expected_fields = custom_expectations["fields"]
        else:
            # Default expected fields derived from resolved parameters and action context
            expected_fields = {
                k: v for k, v in step.resolved_parameters.items()
                if v and k not in ("file_name", "filename")
            }
            if not expected_fields:
                expected_fields = {"action": step.action}

        checks.append(
            VerificationCheck(
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="structured_json_fields",
                strategy_type=VerificationStrategyType.STRUCTURED_OUTPUT,
                target=str(target_name),
                expected_state=expected_fields,
                actual_state={},
                status=VerificationStatus.PENDING,
                reason="Structured JSON field verification pending",
            )
        )

        return checks

    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
    ) -> VerificationCheck:
        """Deterministically inspects and compares JSON file contents."""
        now_iso = datetime.now(timezone.utc).isoformat()
        check.checked_at = now_iso

        is_safe, resolved_path, err_msg = self._resolve_and_verify_sandbox_path(check.target, sandbox_root)
        if not is_safe or resolved_path is None:
            check.status = VerificationStatus.FAILED
            check.actual_state = {"error": err_msg, "safe_sandbox": False}
            check.reason = f"Sandbox security violation: {err_msg}"
            check.evidence = {"attempted_target": check.target, "error": err_msg, "checked_at": now_iso}
            return check

        if not resolved_path.exists() or not resolved_path.is_file():
            check.status = VerificationStatus.FAILED
            check.actual_state = {"file_exists": False}
            check.reason = f"JSON file '{resolved_path.name}' does not exist inside sandbox"
            check.evidence = {"path": str(resolved_path), "exists": False, "checked_at": now_iso}
            return check

        # Parse JSON
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                actual_data = json.load(f)
        except Exception as e:
            check.status = VerificationStatus.FAILED
            check.actual_state = {"json_parse_error": str(e)}
            check.reason = f"Failed to parse JSON file '{resolved_path.name}': {str(e)}"
            check.evidence = {"path": str(resolved_path), "parse_error": str(e), "checked_at": now_iso}
            return check

        if not isinstance(actual_data, dict):
            check.status = VerificationStatus.FAILED
            check.actual_state = {"actual_type": type(actual_data).__name__}
            check.reason = f"Expected JSON dictionary payload, but got {type(actual_data).__name__}"
            check.evidence = {"path": str(resolved_path), "actual_type": type(actual_data).__name__, "checked_at": now_iso}
            return check

        # Compare expected key-values
        expected_fields: Dict[str, Any] = check.expected_state if isinstance(check.expected_state, dict) else {}
        matched_fields: List[str] = []
        mismatched_fields: List[Dict[str, Any]] = []
        missing_fields: List[str] = []

        for exp_key, exp_val in expected_fields.items():
            if exp_key in actual_data:
                actual_val = actual_data[exp_key]
            elif isinstance(actual_data.get("parameters"), dict) and exp_key in actual_data["parameters"]:
                actual_val = actual_data["parameters"][exp_key]
            else:
                missing_fields.append(exp_key)
                continue

            # Compare as strings or exact types
            if str(actual_val).strip() == str(exp_val).strip():
                matched_fields.append(exp_key)
            else:
                mismatched_fields.append({
                    "field": exp_key,
                    "expected": exp_val,
                    "actual": actual_val,
                })

        check.actual_state = {
            "fields_found": list(actual_data.keys()),
            "matched_fields": matched_fields,
            "mismatched_fields": mismatched_fields,
            "missing_fields": missing_fields,
        }

        check.evidence = {
            "path": str(resolved_path),
            "total_actual_fields": len(actual_data),
            "matched_count": len(matched_fields),
            "mismatch_count": len(mismatched_fields),
            "missing_count": len(missing_fields),
            "checked_at": now_iso,
        }

        if missing_fields:
            check.status = VerificationStatus.FAILED
            check.reason = f"Missing expected field(s) in JSON: {', '.join(missing_fields)}"
            return check

        if mismatched_fields:
            check.status = VerificationStatus.FAILED
            diff_desc = "; ".join(f"'{m['field']}': expected '{m['expected']}' but got '{m['actual']}'" for m in mismatched_fields)
            check.reason = f"Structured value mismatch: {diff_desc}"
            return check

        check.status = VerificationStatus.VERIFIED
        check.reason = f"Verified: All {len(matched_fields)} expected structured fields matched in '{resolved_path.name}'"
        return check
