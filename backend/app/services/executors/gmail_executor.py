"""Gmail API Executor (Phase 12 & Phase 15A).

Implements real external execution integrations for Gmail:
- search_email: Read-only search returning normalized message summaries.
- download_attachment: Download an email attachment to a controlled WorkFlowOS sandbox directory.

Declares:
- strategy_type: API_INTEGRATION
- implemented: True
- requires_external_access: True
- supports_verification: True
- priority: 1

SECURITY BOUNDARIES:
- Strictly read-only operations on Gmail: ZERO mutations on Gmail (no send, delete, move, label, mark-as-read).
- Attachment files are written ONLY to the WorkFlowOS-managed sandbox directory.
- Rejects path traversal (..), absolute path injection, or writing outside the controlled directory.
- Never falls back to ControlledLocalExecutor for Gmail operations.
- Fails closed with standardized codes (INTEGRATION_UNAVAILABLE, AUTHENTICATION_REQUIRED, INVALID_PARAMETER, SECURITY_VIOLATION).
- Never leaks or logs OAuth tokens, client secrets, or Authorization headers.
"""

from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models.canonical import RiskLevel
from app.models.execution import (
    ExecutionContext,
    ExecutionStepResult,
    ExecutionStepStatus,
)
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability
from app.services.executors.base import BaseExecutor
from app.services.gmail_client import (
    GmailApiClient,
    GmailApiError,
    GmailAuthenticationError,
    GmailConfigurationError,
)

logger = logging.getLogger(__name__)


class GmailApiExecutor(BaseExecutor):
    """Executor executing verified read-only operations against Google Gmail API."""

    def __init__(self, client: Optional[GmailApiClient] = None) -> None:
        self.client = client or GmailApiClient()

    @property
    def name(self) -> str:
        return "GmailApiExecutor"

    @property
    def strategy(self) -> ExecutionStrategy:
        return ExecutionStrategy.API

    @property
    def capability(self) -> ExecutorCapability:
        return ExecutorCapability(
            executor_name=self.name,
            strategy_type=ExecutionStrategyType.API_INTEGRATION,
            supported_actions=["search_email", "download_attachment"],
            supported_targets=["Gmail", "gmail", "Google Mail"],
            supported_risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            implemented=True,
            requires_external_access=True,
            supports_verification=True,
            priority=1,
            description="Gmail API executor for deterministic read-only operations (search_email, download_attachment).",
        )

    def supports(self, strategy: Any) -> bool:
        strat_str = str(strategy.value if hasattr(strategy, "value") else strategy).upper()
        return strat_str in ("API", "API_INTEGRATION", ExecutionStrategyType.API_INTEGRATION.value)

    @staticmethod
    def _sanitize_filename(name: Optional[str]) -> str:
        """Sanitizes an attachment filename to prevent directory traversal or hidden files."""
        if not name or not str(name).strip():
            return "attachment.bin"
        clean = os.path.basename(str(name).strip().replace("\\", "/"))
        clean = clean.replace("..", "").strip()
        if not clean or clean in (".", ".."):
            return "attachment.bin"
        return clean

    @staticmethod
    def _resolve_and_verify_destination(
        target_path_str: Optional[str],
        filename: str,
        sandbox_root: str,
    ) -> Tuple[bool, Optional[Path], str]:
        """Resolves target path inside sandbox_root and verifies absence of path traversal or escape."""
        try:
            sandbox_real = Path(sandbox_root).resolve()

            if target_path_str:
                norm_target = target_path_str.replace("\\", "/")
                if ".." in norm_target.split("/"):
                    return False, None, f"Path traversal rejected: '{target_path_str}' contains '..'"
                target_p = Path(target_path_str)
                if target_p.is_absolute():
                    resolved = target_p.resolve()
                else:
                    resolved = (sandbox_real / target_p).resolve()
            else:
                att_dir = (sandbox_real / "attachments").resolve()
                att_dir.mkdir(parents=True, exist_ok=True)
                resolved = (att_dir / filename).resolve()

            # Ensure resolved path is strictly within sandbox_real
            try:
                resolved.relative_to(sandbox_real)
            except ValueError:
                return False, None, f"Target destination '{resolved}' escapes controlled sandbox '{sandbox_real}'"

            return True, resolved, ""
        except Exception as e:
            return False, None, f"Path resolution error: {str(e)}"

    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        """Strictly validates safety guardrails on the planned step before Gmail execution."""
        errors: List[str] = []

        # 1. Action check
        act_norm = step.action.lower().strip().replace(" ", "_")
        if act_norm not in ("search_email", "download_attachment", "download_email_attachment"):
            errors.append(f"GmailApiExecutor only supports 'search_email' and 'download_attachment'. Given: '{step.action}'")

        # 2. Target check
        app_norm = step.application.lower().strip()
        if not any(t in app_norm for t in ["gmail", "google mail"]):
            errors.append(f"GmailApiExecutor only targets Gmail. Given application: '{step.application}'")

        # 3. Parameter check
        resolved_params = context.resolved_parameters or {}
        if act_norm == "search_email":
            query = (
                resolved_params.get("query")
                or resolved_params.get("search_query")
                or resolved_params.get("q")
            )
            if not query or not str(query).strip():
                errors.append("Missing required 'query' parameter for Gmail search")
        elif act_norm in ("download_attachment", "download_email_attachment"):
            msg_id = (
                resolved_params.get("message_id")
                or resolved_params.get("msg_id")
                or resolved_params.get("id")
            )
            if (not msg_id or not str(msg_id).strip()) and not context.dry_run:
                errors.append("Missing required 'message_id' parameter for download_attachment")

            # Check for path traversal in target_path or filename
            target_path = resolved_params.get("target_path") or resolved_params.get("destination_path")
            if target_path and ".." in str(target_path).replace("\\", "/").split("/"):
                errors.append(f"Path traversal detected in target_path: '{target_path}'")
            filename = resolved_params.get("filename") or resolved_params.get("attachment_filename")
            if filename and ".." in str(filename).replace("\\", "/").split("/"):
                errors.append(f"Path traversal detected in filename: '{filename}'")

        return len(errors) == 0, errors

    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        """Executes a single read-only operation via the Gmail API."""
        start_time = datetime.now(timezone.utc).isoformat()
        act_norm = step.action.lower().strip().replace(" ", "_")

        # 1. Action Validation
        if act_norm not in ("search_email", "download_attachment", "download_email_attachment"):
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="UNSUPPORTED_ACTION",
                error=f"GmailApiExecutor only supports 'search_email' and 'download_attachment'. Action '{step.action}' is not supported.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        resolved_params = context.resolved_parameters or {}

        # 2. Dry-run Mode Check (0 real actions, 0 external API calls)
        if context.dry_run:
            if act_norm == "search_email":
                query_str = str(
                    resolved_params.get("query")
                    or resolved_params.get("search_query")
                    or resolved_params.get("q")
                    or "simulated_query"
                )
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.SUCCESS,
                    parameters_used={"query": query_str, "dry_run": True},
                    output={
                        "operation": "search_email",
                        "query": query_str,
                        "total_found": 1,
                        "messages": [
                            {
                                "message_id": "msg-simulated-dry-run",
                                "subject": "Simulated Support Request",
                                "sender": "customer@example.com",
                            }
                        ],
                        "message_id": "msg-simulated-dry-run",
                        "status": "SIMULATED",
                    },
                    affected_resources=[],
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    selection_reason="Simulated read-only search via Gmail API (dry run)",
                    notes="Dry run simulation: Real Gmail API search was NOT performed. 0 external actions.",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )
            else:
                msg_id_sim = str(
                    resolved_params.get("message_id")
                    or resolved_params.get("msg_id")
                    or "msg-simulated"
                )
                raw_filename_sim = (
                    resolved_params.get("filename")
                    or resolved_params.get("attachment_filename")
                    or "attachment.bin"
                )
                safe_name_sim = self._sanitize_filename(raw_filename_sim)
                sim_dest = str(Path(context.sandbox_root) / "attachments" / safe_name_sim)
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.SUCCESS,
                    parameters_used={
                        "message_id": msg_id_sim,
                        "filename": safe_name_sim,
                        "dry_run": True,
                    },
                    output={
                        "operation": "download_attachment",
                        "message_id": msg_id_sim,
                        "expected_filename": safe_name_sim,
                        "expected_destination": sim_dest,
                        "saved_path": sim_dest,
                        "downloaded_file": sim_dest,
                        "status": "SIMULATED",
                    },
                    affected_resources=[],
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    selection_reason="Simulated attachment download via Gmail API (dry run)",
                    notes="Dry run simulation: Real Gmail API attachment download was NOT performed. 0 external actions.",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )

        # 3. Branch by Action: search_email vs download_attachment
        if act_norm == "search_email":
            return self._execute_search_email(step, context, start_time)
        else:
            return self._execute_download_attachment(step, context, start_time)

    def _execute_search_email(
        self,
        step: PlannedStep,
        context: ExecutionContext,
        start_time: str,
    ) -> ExecutionStepResult:
        """Executes search_email operation."""
        resolved_params = context.resolved_parameters or {}
        query = (
            resolved_params.get("query")
            or resolved_params.get("search_query")
            or resolved_params.get("q")
        )

        if not query or not str(query).strip():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INVALID_PARAMETER",
                error="Required parameter 'query' is missing or empty for search_email operation.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        query_str = str(query).strip()

        # Check Configuration & Authentication (Fail-Closed)
        if not self.client.is_configured():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error="Gmail API integration is not configured. Provide GMAIL_CREDENTIALS_PATH or GMAIL_TOKEN_PATH.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        if not self.client.is_authenticated():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error="Gmail OAuth 2.0 authorization is required. Valid credentials or token not found.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        try:
            max_results = int(resolved_params.get("max_results", 10))
            search_result = self.client.search_messages(query=query_str, max_results=max_results)

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={"query": query_str, "max_results": max_results},
                output={
                    "query": query_str,
                    "total_found": search_result.total_found,
                    "messages": [m.model_dump() for m in search_result.messages],
                    "searched_at": search_result.searched_at,
                    "operation": "search_email",
                    "status": "COMPLETED",
                },
                affected_resources=[],  # Strictly read-only
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason="Executed read-only search via Gmail API",
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except GmailConfigurationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error=f"Gmail configuration error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except GmailAuthenticationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error=f"Gmail authentication required: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error("GmailApiExecutor search execution failed: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Gmail API execution error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

    def _execute_download_attachment(
        self,
        step: PlannedStep,
        context: ExecutionContext,
        start_time: str,
    ) -> ExecutionStepResult:
        """Executes download_attachment operation, saving strictly inside the controlled sandbox."""
        resolved_params = context.resolved_parameters or {}

        # 1. Message ID Validation
        msg_id = (
            resolved_params.get("message_id")
            or resolved_params.get("msg_id")
            or resolved_params.get("id")
        )
        if not msg_id or not str(msg_id).strip():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INVALID_PARAMETER",
                error="Required parameter 'message_id' is missing or empty for download_attachment operation.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        msg_id_clean = str(msg_id).strip()
        attachment_id = resolved_params.get("attachment_id") or resolved_params.get("att_id")
        target_path_param = resolved_params.get("target_path") or resolved_params.get("destination_path")
        raw_filename = (
            resolved_params.get("filename")
            or resolved_params.get("attachment_filename")
            or resolved_params.get("file_name")
        )

        # 2. Path Traversal & Destination Security Checks
        if raw_filename and (".." in str(raw_filename).replace("\\", "/").split("/")):
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="SECURITY_VIOLATION",
                error=f"Path traversal rejected in filename: '{raw_filename}' contains '..'",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        if target_path_param:
            norm_tp = str(target_path_param).replace("\\", "/")
            if ".." in norm_tp.split("/"):
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.BLOCKED,
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    blocked_reason="SECURITY_VIOLATION",
                    error=f"Path traversal rejected in destination path: '{target_path_param}' contains '..'",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )
            tp_obj = Path(target_path_param)
            if tp_obj.is_absolute():
                sandbox_real = Path(context.sandbox_root).resolve()
                try:
                    tp_obj.resolve().relative_to(sandbox_real)
                except ValueError:
                    return ExecutionStepResult(
                        planned_step_id=step.plan_step_id,
                        action_name=step.action,
                        target_application=step.application,
                        strategy=self.strategy,
                        executor_name=self.name,
                        status=ExecutionStepStatus.BLOCKED,
                        selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                        blocked_reason="SECURITY_VIOLATION",
                        error=f"Absolute path injection rejected: destination '{target_path_param}' is outside controlled sandbox '{sandbox_real}'",
                        start_time=start_time,
                        end_time=datetime.now(timezone.utc).isoformat(),
                    )

        # 3. Check Configuration & Authentication (Fail-Closed)
        if not self.client.is_configured():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error="Gmail API integration is not configured. Provide GMAIL_CREDENTIALS_PATH or GMAIL_TOKEN_PATH.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        if not self.client.is_authenticated():
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error="Gmail OAuth 2.0 authorization is required. Valid credentials or token not found.",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        # 4. Perform Download via Gmail API Client
        try:
            clean_filename = self._sanitize_filename(raw_filename) if raw_filename else None
            try:
                file_bytes, metadata = self.client.download_attachment(
                    message_id=msg_id_clean,
                    attachment_id=str(attachment_id).strip() if attachment_id else None,
                    filename=clean_filename,
                )
            except GmailApiError as ge:
                if clean_filename and "No attachment matching" in str(ge):
                    logger.info("Attachment '%s' not found in message '%s', discovering actual attachment", clean_filename, msg_id_clean)
                    file_bytes, metadata = self.client.download_attachment(
                        message_id=msg_id_clean,
                        attachment_id=str(attachment_id).strip() if attachment_id else None,
                        filename=None,
                    )
                else:
                    raise

            safe_final_name = self._sanitize_filename(metadata.get("filename") or clean_filename or "attachment.bin")
            is_safe, resolved_path, err_msg = self._resolve_and_verify_destination(
                target_path_str=str(target_path_param) if target_path_param else None,
                filename=safe_final_name,
                sandbox_root=context.sandbox_root,
            )
            if not is_safe or not resolved_path:
                return ExecutionStepResult(
                    planned_step_id=step.plan_step_id,
                    action_name=step.action,
                    target_application=step.application,
                    strategy=self.strategy,
                    executor_name=self.name,
                    status=ExecutionStepStatus.BLOCKED,
                    selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                    blocked_reason="SECURITY_VIOLATION",
                    error=f"Destination containment violation: {err_msg}",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc).isoformat(),
                )

            # Write bytes safely to controlled location
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved_path, "wb") as f:
                f.write(file_bytes)

            file_sha256 = hashlib.sha256(file_bytes).hexdigest()

            msg_id_val = metadata.get("message_id") or msg_id_clean
            att_id_val = metadata.get("attachment_id") or str(attachment_id or "att-1")

            output = {
                "operation": "download_attachment",
                "message_id": msg_id_val,
                "attachment_id": att_id_val,
                "filename": safe_final_name,
                "mime_type": metadata.get("mime_type"),
                "size_bytes": len(file_bytes),
                "saved_path": str(resolved_path),
                "sha256": file_sha256,
                "status": "COMPLETED",
            }

            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.SUCCESS,
                parameters_used={
                    "message_id": msg_id_val,
                    "attachment_id": att_id_val,
                    "filename": safe_final_name,
                },
                output=output,
                affected_resources=[str(resolved_path)],
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                selection_reason="Downloaded attachment from Gmail to controlled sandbox destination",
                fallback_used=False,
                policy_decision="ALLOWED",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )

        except GmailConfigurationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="INTEGRATION_UNAVAILABLE",
                error=f"Gmail configuration error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except GmailAuthenticationError as e:
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.BLOCKED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                blocked_reason="AUTHENTICATION_REQUIRED",
                error=f"Gmail authentication required: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except GmailApiError as e:
            logger.error("GmailApiExecutor download API error: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Gmail attachment download error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error("GmailApiExecutor download unexpected error: %s", str(e))
            return ExecutionStepResult(
                planned_step_id=step.plan_step_id,
                action_name=step.action,
                target_application=step.application,
                strategy=self.strategy,
                executor_name=self.name,
                status=ExecutionStepStatus.FAILED,
                selected_strategy=ExecutionStrategyType.API_INTEGRATION.value,
                error=f"Gmail API execution error: {str(e)}",
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
            )
