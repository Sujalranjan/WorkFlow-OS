"""Independent check for sheets.append_row: read the added row back and compare it."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import VerificationCheck, VerificationStatus, VerificationStrategyType
from app.services import google_sheets
from app.services.verifiers.base import BaseVerificationStrategy


def _trim(row: List[str]) -> List[str]:
    """Sheets omits trailing empty cells when reading."""
    out = [str(c) for c in row]
    while out and out[-1] == "":
        out.pop()
    return out


class GoogleSheetsVerificationStrategy(BaseVerificationStrategy):
    def __init__(self, client: Optional[google_sheets.GoogleSheetsClient] = None) -> None:
        self.client = client or google_sheets.GoogleSheetsClient()

    @property
    def name(self) -> str:
        return "GoogleSheetsVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        return step_result.executor_name == "GoogleSheetsExecutor"

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        output = step_result.output or {}
        return [
            VerificationCheck(
                verification_id=f"vchk-sheets-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="sheets_row_appended",
                strategy_type=self.strategy_type,
                target=f"Sheets:{output.get('spreadsheet_id') or 'unknown'}:{output.get('updated_range') or 'unknown'}",
                expected_state={k: output.get(k) for k in ("spreadsheet_id", "updated_range", "row")},
                actual_state={"status": step_result.status.value, "error": step_result.error, "output": output},
                status=VerificationStatus.PENDING,
                reason="Reading the added row back from Google Sheets",
            )
        ]

    def verify(self, check: VerificationCheck, sandbox_root: str) -> VerificationCheck:
        check.checked_at = datetime.now(timezone.utc).isoformat()
        state = check.actual_state if isinstance(check.actual_state, dict) else {}
        expected = check.expected_state if isinstance(check.expected_state, dict) else {}
        if state.get("status") == ExecutionStepStatus.BLOCKED.value:
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "The step was blocked, so no row was added.")
        if state.get("status") == ExecutionStepStatus.FAILED.value:
            return self._set(check, VerificationStatus.FAILED, f"Adding the row failed: {state.get('error')}")
        if (state.get("output") or {}).get("status") == "SIMULATED":
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "Dry run: no row was added.")
        spreadsheet_id, a1_range, row = expected.get("spreadsheet_id"), expected.get("updated_range"), expected.get("row")
        if not spreadsheet_id or not a1_range or row is None:
            return self._set(check, VerificationStatus.FAILED, "The step reported no row.")
        try:
            values = self.client.read_range(str(spreadsheet_id), str(a1_range))
        except google_sheets.SheetsError as e:
            return self._set(check, VerificationStatus.UNKNOWN, str(e))
        actual = _trim(values[0]) if values else []
        check.evidence = {"range": a1_range, "values": actual}
        if actual == _trim(row):
            return self._set(check, VerificationStatus.VERIFIED, f"Google Sheets shows the row at {a1_range}.")
        return self._set(check, VerificationStatus.FAILED, f"The row at {a1_range} differs from what was added.")

    @staticmethod
    def _set(check: VerificationCheck, status: VerificationStatus, reason: str) -> VerificationCheck:
        check.status = status
        check.reason = reason
        return check
