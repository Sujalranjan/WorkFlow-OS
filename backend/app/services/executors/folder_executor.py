"""Shared-folder executor: copy the file this run downloaded into the folder chosen in Settings.

Never overwrites (a taken name becomes 'name (2).ext'), never copies anything from outside the
run's sandbox, and makes no change on a dry run. Missing setup is BLOCKED before anything happens.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import ExecutionContext, ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services import shared_folder
from app.services.executors.base import BaseExecutor

ACTIONS = ("save_to_folder",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SharedFolderExecutor(BaseExecutor):
    @property
    def name(self) -> str:
        return "SharedFolderExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=list(ACTIONS),
            supported_targets=["Files"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=False,
            supports_verification=True,
            priority=1,
            description="Copies the run's downloaded file into the shared folder chosen in Settings.",
        )

    def supports(self, strategy: Any) -> bool:
        value = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return value in ("API", ExecutionStrategyType.API_INTEGRATION.value)

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        if step.action not in ACTIONS:
            return False, [f"SharedFolderExecutor does not support '{step.action}'."]
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

    @staticmethod
    def _unresolved(value: Any) -> bool:
        text = str(value or "").strip()
        return not text or (text.startswith("{") and text.endswith("}"))

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        start = _now()
        if step.action not in ACTIONS:
            return self._result(step, start, ExecutionStepStatus.BLOCKED, blocked_reason="UNSUPPORTED_ACTION",
                                error=f"The shared folder cannot '{step.action}'.")
        params: Dict[str, Any] = {**(context.resolved_parameters or {}), **(step.resolved_parameters or {})}
        source_file = params.get("source_file")
        if self._unresolved(source_file):
            source_file = params.get("downloaded_file") or params.get("attachment_path")
        wanted_raw = params.get("file_name")
        if self._unresolved(wanted_raw):
            wanted_raw = params.get("filename") or (Path(str(source_file)).name if source_file else "")

        try:
            folder, source = shared_folder.configured_folder()
            folder_path = shared_folder.check_folder(folder or "")
            wanted = shared_folder.safe_file_name(str(wanted_raw or ""))
            if context.dry_run:
                name, renamed = shared_folder.plan_name(folder_path, wanted)
                return self._result(
                    step, start, ExecutionStepStatus.SUCCESS,
                    parameters_used={"dry_run": True, "file_name": wanted},
                    output={"operation": "save_to_folder", "folder": str(folder_path), "file_name": name,
                            "renamed": renamed, "status": "SIMULATED"},
                    selection_reason="Dry run: nothing was copied.",
                )
            src = shared_folder.resolve_source(str(source_file or ""), context.sandbox_root)
            saved = shared_folder.copy_into(folder_path, src, wanted)
        except shared_folder.SharedFolderError as e:
            return self._result(step, start, ExecutionStepStatus.BLOCKED, blocked_reason=e.code, error=str(e))
        except OSError as e:
            return self._result(step, start, ExecutionStepStatus.FAILED,
                                error=f"Could not copy into the shared folder: {type(e).__name__}: {e.strerror or e}")

        return self._result(
            step, start, ExecutionStepStatus.SUCCESS,
            parameters_used={"file_name": wanted, "folder_source": source},
            output={
                "operation": "save_to_folder",
                "folder": str(folder_path),
                "saved_path": saved.path,
                "file_name": saved.file_name,
                "requested_name": wanted,
                "renamed": saved.renamed,
                "size_bytes": saved.size_bytes,
                "sha256": saved.sha256,
                "status": "COMPLETED",
            },
            affected_resources=[saved.path],
            selection_reason=(
                f"Saved as '{saved.file_name}' ('{wanted}' was already taken)" if saved.renamed else f"Saved as '{saved.file_name}'"
            ),
        )
