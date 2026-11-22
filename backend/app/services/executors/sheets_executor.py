"""sheets.append_row: add one row about this run to the Google Sheet chosen in Settings.

Only the configured spreadsheet is ever written; a workflow recorded against another spreadsheet is
BLOCKED instead of writing there. Dry runs show the row without calling Google.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import ExecutionContext, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services import google_sheets
from app.services.executors.base import BaseExecutor

ACTIONS = ("append_row",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unresolved(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or (text.startswith("{") and text.endswith("}"))


class GoogleSheetsExecutor(BaseExecutor):
    def __init__(self, client: Optional[google_sheets.GoogleSheetsClient] = None) -> None:
        self.client = client or google_sheets.GoogleSheetsClient()

    @property
    def name(self) -> str:
        return "GoogleSheetsExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=list(ACTIONS),
            supported_targets=["Google Sheets"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="Appends a row about the run to the Google Sheet chosen in Settings (never edits existing cells).",
        )

    def supports(self, strategy: Any) -> bool:
        value = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return value in ("API", ExecutionStrategyType.API_INTEGRATION.value)

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        if step.action not in ACTIONS:
            return False, [f"GoogleSheetsExecutor does not support '{step.action}'."]
        return True, []

    def _result(self, step: PlannedStep, start: str, status: ExecutionStepStatus, **fields) -> ExecutionStepResult:
        return ExecutionStepResult(
            planned_step_id=step.plan_step_id,
            action_name=step.action,
            target_application=step.application,
            strategy=self.strategy,
            executor_name=self.name,
            status=status,
            selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
            policy_decision="BLOCKED" if status == ExecutionStepStatus.BLOCKED else "ALLOWED",
            start_time=start,
            end_time=_now(),
            **fields,
        )

    def _blocked(self, step, start, reason: str, error: str) -> ExecutionStepResult:
        return self._result(step, start, ExecutionStepStatus.BLOCKED, blocked_reason=reason, error=error)

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        start = _now()
        if step.action not in ACTIONS:
            return self._blocked(step, start, "UNSUPPORTED_ACTION", f"Google Sheets cannot '{step.action}'.")
        params = {
            **(context.resolved_parameters or {}),
            **{k: v for k, v in (step.resolved_parameters or {}).items() if not _unresolved(v)},
            "execution_id": context.execution_id,
            "workflow_id": context.workflow_id,
        }
        sheet = google_sheets.configured_sheet()
        if not sheet:
            return self._blocked(step, start, "NOT_CONFIGURED", "Choose the Google Sheet in Settings > Integrations > Google Sheets.")
        recorded = step.resolved_parameters.get("spreadsheet_id") if step.resolved_parameters else None
        if not _unresolved(recorded) and str(recorded) != sheet["spreadsheet_id"]:
            return self._blocked(
                step, start, "NOT_CONFIGURED",
                f"This workflow was recorded with another spreadsheet ({recorded}); Settings has "
                f"'{sheet.get('title')}'. Choose that spreadsheet in Settings, or re-record the workflow.",
            )
        columns = list(sheet.get("columns") or google_sheets.DEFAULT_COLUMNS)
        row = google_sheets.build_row(columns, params)
        base_output = {
            "operation": "append_row",
            "spreadsheet_id": sheet["spreadsheet_id"],
            "spreadsheet_title": sheet.get("title"),
            "sheet": sheet["sheet"],
            "columns": columns,
            "row": row,
        }
        if context.dry_run:
            return self._result(
                step, start, ExecutionStepStatus.SUCCESS,
                parameters_used={"dry_run": True},
                output={**base_output, "status": "SIMULATED"},
                selection_reason="Dry run: the row was not added.",
            )
        try:
            updated_range = self.client.append_row(sheet["spreadsheet_id"], sheet["sheet"], row)
        except google_sheets.SheetsError as e:
            if isinstance(e, (google_sheets.SheetsNotAllowed, google_sheets.SheetNotConfigured)):
                return self._blocked(step, start, e.code, str(e))
            return self._result(step, start, ExecutionStepStatus.FAILED, error=str(e))
        return self._result(
            step, start, ExecutionStepStatus.SUCCESS,
            parameters_used={"spreadsheet_id": sheet["spreadsheet_id"], "sheet": sheet["sheet"]},
            output={**base_output, "updated_range": updated_range, "status": "COMPLETED"},
            affected_resources=[f"sheets:{sheet['spreadsheet_id']}:{updated_range}"],
            selection_reason=f"Added a row to '{sheet.get('title')}' ({updated_range})",
        )
