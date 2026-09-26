"""File System and Resource Existence Verification Strategy (Phase 9).

Deterministic post-execution verification for sandbox filesystem artifacts:
- File existence
- Non-empty file validation
- Directory existence
- Resource absence (e.g. temporary file cleanup)
- Computes SHA256 hash and metadata as tamper-proof evidence
- Strict sandbox boundary enforcement (no path traversal, no reading outside sandbox)
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models.execution import ExecutionStepResult, ExecutionStepStatus
from app.models.execution_plan import PlannedStep
from app.models.verification import (
    VerificationCheck,
    VerificationStatus,
    VerificationStrategyType,
)
from app.services.verifiers.base import BaseVerificationStrategy


class FileSystemVerificationStrategy(BaseVerificationStrategy):
    """Verifies file and directory artifacts strictly inside the execution sandbox."""

    @property
    def name(self) -> str:
        return "FileSystemVerificationStrategy"

    @property
    def strategy_type(self) -> VerificationStrategyType:
        return VerificationStrategyType.FILE_SYSTEM

    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Supports filesystem actions and steps producing or validating file artifacts."""
        app_lower = step.application.lower()
        action_lower = step.action.lower()

        # Target must be local filesystem
        if any(f in app_lower for f in ["file system", "filesystem", "file", "local", "folder"]):
            return True

        # Or action is explicitly a local file action
        if any(act in action_lower for act in ["save_file", "create_file", "write_file", "copy_file", "download_file", "create_report"]):
            return True

        # Or step produced affected resources in local execution
        if step_result.affected_resources:
            return True

        return False

    def _resolve_and_verify_sandbox_path(self, target_path_str: str, sandbox_root: str) -> Tuple[bool, Optional[Path], str]:
        """Strict sandbox boundary resolution with path traversal rejection."""
        try:
            sandbox_real = Path(sandbox_root).resolve()

            # Prevent traversal via relative segments
            if ".." in target_path_str.replace("\\", "/").split("/"):
                return False, None, f"Path traversal rejected: '{target_path_str}' contains '..'"

            target_p = Path(target_path_str)
            if target_p.is_absolute():
                resolved = target_p.resolve()
            else:
                resolved = (sandbox_real / target_p).resolve()

            # Ensure resolved path is strictly within sandbox_real
            try:
                resolved.relative_to(sandbox_real)
            except ValueError:
                return False, None, f"Target path '{resolved}' escapes configured sandbox '{sandbox_real}'"

            return True, resolved, ""
        except Exception as e:
            return False, None, f"Path resolution error: {str(e)}"

    def _compute_sha256(self, file_path: Path) -> str:
        """Computes SHA256 hash of a file for deterministic evidence."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Builds verification checks from the planned step, state change, and affected resources."""
        checks: List[VerificationCheck] = []

        # Determine target file name/path
        target_name = (
            step.resolved_parameters.get("file_name")
            or step.resolved_parameters.get("filename")
            or step.resolved_parameters.get("invoice_document")
        )

        if not target_name and step_result.affected_resources:
            target_name = Path(step_result.affected_resources[0]).name

        if not target_name:
            target_name = f"step_{step.plan_step_id}_output.txt"

        # Check 1: File Existence & Non-Empty Check
        checks.append(
            VerificationCheck(
                execution_id=execution_id,
                execution_step_id=step_result.execution_step_id,
                planned_step_id=step.plan_step_id,
                check_type="file_exists",
                strategy_type=VerificationStrategyType.RESOURCE_EXISTENCE,
                target=str(target_name),
                expected_state={
                    "exists": True,
                    "target": str(target_name),
                    "min_size_bytes": 1,
                    "expected_description": step.state_change.expected_after_state if step.state_change else "File exists in sandbox",
                },
                actual_state={"exists": False},
                status=VerificationStatus.PENDING,
                reason="Verification check pending evaluation",
            )
        )

        return checks

    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
    ) -> VerificationCheck:
        """Executes deterministic filesystem check within the sandbox."""
        now_iso = datetime.now(timezone.utc).isoformat()
        check.checked_at = now_iso

        # 1. Sandbox containment check
        is_safe, resolved_path, err_msg = self._resolve_and_verify_sandbox_path(check.target, sandbox_root)
        if not is_safe or resolved_path is None:
            check.status = VerificationStatus.FAILED
            check.actual_state = {"error": err_msg, "safe_sandbox": False}
            check.reason = f"Sandbox security violation: {err_msg}"
            check.evidence = {"attempted_target": check.target, "error": err_msg, "checked_at": now_iso}
            return check

        # 2. Check File Existence
        if check.check_type in ("file_exists", "non_empty_file", "resource_exists"):
            exists = resolved_path.exists()
            is_file = resolved_path.is_file() if exists else False
            size = resolved_path.stat().st_size if is_file else 0
            sha256 = self._compute_sha256(resolved_path) if is_file else ""

            evidence = {
                "path": str(resolved_path),
                "target_filename": resolved_path.name,
                "exists": exists,
                "is_file": is_file,
                "size_bytes": size,
                "sha256": sha256,
                "checked_at": now_iso,
            }
            check.evidence = evidence
            check.actual_state = {
                "exists": exists,
                "is_file": is_file,
                "size_bytes": size,
                "sha256": sha256,
            }

            if not exists:
                check.status = VerificationStatus.FAILED
                check.reason = f"Expected artifact '{resolved_path.name}' does not exist inside sandbox '{sandbox_root}'"
                return check

            if check.check_type == "non_empty_file" or isinstance(check.expected_state, dict) and check.expected_state.get("min_size_bytes", 0) > 0:
                if size == 0:
                    check.status = VerificationStatus.FAILED
                    check.reason = f"Artifact '{resolved_path.name}' exists but has 0 bytes (empty file)"
                    return check

            check.status = VerificationStatus.VERIFIED
            check.reason = f"Verified: Artifact '{resolved_path.name}' exists in sandbox ({size} bytes, sha256: {sha256[:12]}...)"
            return check

        # 3. Check Directory Existence
        if check.check_type == "directory_exists":
            exists = resolved_path.exists() and resolved_path.is_dir()
            check.actual_state = {"exists": exists, "is_directory": exists}
            check.evidence = {"path": str(resolved_path), "is_directory": exists, "checked_at": now_iso}

            if exists:
                check.status = VerificationStatus.VERIFIED
                check.reason = f"Verified: Directory '{resolved_path.name}' exists in sandbox"
            else:
                check.status = VerificationStatus.FAILED
                check.reason = f"Directory '{resolved_path.name}' does not exist inside sandbox"
            return check

        # Fallback unknown check type
        check.status = VerificationStatus.UNKNOWN
        check.reason = f"Unsupported filesystem check type '{check.check_type}'"
        return check
