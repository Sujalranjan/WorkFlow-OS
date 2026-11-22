"""Independent check for save_to_folder: the copy exists in the shared folder with the same content."""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import VerificationCheck, VerificationStatus, VerificationStrategyType
from app.services import shared_folder
from app.services.verifiers.base import BaseVerificationStrategy


class SharedFolderVerificationStrategy(BaseVerificationStrategy):
    @property
    def name(self) -> str:
        return "SharedFolderVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.STATE_MATCH

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        return step_result.executor_name == "SharedFolderExecutor"

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
                verification_id=f"vchk-fs-{uuid.uuid4().hex[:8]}",
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="shared_folder_file_saved",
                strategy_type=self.strategy_type,
                target=f"Files:{output.get('file_name') or 'unknown'}",
                expected_state={k: output.get(k) for k in ("folder", "saved_path", "file_name", "sha256", "size_bytes")},
                actual_state={"status": step_result.status.value, "error": step_result.error, "output": output},
                status=VerificationStatus.PENDING,
                reason="Re-reading the shared folder to confirm the copy",
            )
        ]

    def verify(self, check: VerificationCheck, sandbox_root: str) -> VerificationCheck:
        check.checked_at = datetime.now(timezone.utc).isoformat()
        state = check.actual_state if isinstance(check.actual_state, dict) else {}
        expected = check.expected_state if isinstance(check.expected_state, dict) else {}
        if state.get("status") == ExecutionStepStatus.BLOCKED.value:
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "The step was blocked, so nothing was copied.")
        if state.get("status") == ExecutionStepStatus.FAILED.value:
            return self._set(check, VerificationStatus.FAILED, f"The copy failed: {state.get('error')}")
        if (state.get("output") or {}).get("status") == "SIMULATED":
            return self._set(check, VerificationStatus.NOT_APPLICABLE, "Dry run: nothing was copied.")

        path, folder = expected.get("saved_path"), expected.get("folder")
        if not path or not folder:
            return self._set(check, VerificationStatus.FAILED, "The step reported no saved file.")
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(Path(folder).resolve())
        except ValueError:
            return self._set(check, VerificationStatus.FAILED, "The saved file is outside the shared folder.")
        if not resolved.is_file():
            return self._set(check, VerificationStatus.FAILED, f"{expected.get('file_name')} is no longer in the shared folder.")
        actual = shared_folder.sha256_of(str(resolved))
        check.evidence = {"path": str(resolved), "size_bytes": os.path.getsize(resolved), "sha256": actual}
        if actual != expected.get("sha256"):
            return self._set(check, VerificationStatus.FAILED, "The file in the shared folder differs from the downloaded one.")
        return self._set(check, VerificationStatus.VERIFIED, f"{expected.get('file_name')} is in the shared folder, content matches.")

    @staticmethod
    def _set(check: VerificationCheck, status: VerificationStatus, reason: str) -> VerificationCheck:
        check.status = status
        check.reason = reason
        return check
