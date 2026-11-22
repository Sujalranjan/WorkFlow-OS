"""Email triggers: turn new Gmail messages into runs of an approved workflow.

Flow for one trigger:

    poll()         incremental and read-only: Gmail's change log says whether any message arrived
                   since the last complete sync; only then are the ids matching
                   "(<query>) after:<last sync - margin>" listed (every page). Each id not yet in the
                   workflow_runs ledger becomes a WorkflowRun in PENDING_APPROVAL, oldest first, up to
                   MAX_NEW_RUNS_PER_POLL; the rest wait for the next poll. Nothing runs.
    approve_run()  a person approves that run -> ExecutionPlanner (search_query + trigger_message_id)
                   -> ExecutionEngine (LIVE) -> VerificationEngine -> LearningEngine.
    resume_run()   if a step paused with NEEDS_INPUT (e.g. no CRM customer), a person supplies the
                   value and the same execution continues from that step.

No step is ever executed without a per-run human decision, and the Gmail scope stays read-only.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Callable, Dict, List, Optional

from app.models.automation import (
    CreateTriggerRequest,
    EmailTrigger,
    PollResult,
    RunStatus,
    SourceEmail,
    UpdateTriggerRequest,
    WorkflowRun,
)
from app.models.canonical import ApprovalState
from app.models.execution import ExecutionAuditRecord, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.repositories.automation_repository import AutomationRepository
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.services.execution_engine import ExecutionEngine
from app.services.execution_planner import ExecutionPlanner
from app.services.gmail_client import GmailApiClient, GmailHistoryExpired

logger = logging.getLogger(__name__)

GMAIL_TRIGGER_ACTION = "gmail.search_email"
# New runs queued per poll; a larger backlog is worked through on the following polls.
MAX_NEW_RUNS_PER_POLL = 50
# Searches reach back this far before the last sync, covering clock skew and late Gmail indexing.
SYNC_OVERLAP_SECONDS = 600

_RUN_STATUS_FROM_EXECUTION = {
    ExecutionOverallStatus.COMPLETED: RunStatus.COMPLETED,
    ExecutionOverallStatus.NEEDS_INPUT: RunStatus.NEEDS_INPUT,
    ExecutionOverallStatus.BLOCKED: RunStatus.BLOCKED,
    ExecutionOverallStatus.FAILED: RunStatus.FAILED,
    ExecutionOverallStatus.CANCELLED: RunStatus.REJECTED,
}


class TriggerError(ValueError):
    """A trigger or run request that cannot be honoured (maps to HTTP 400/409)."""


class TriggerService:
    def __init__(
        self,
        repo: Optional[AutomationRepository] = None,
        spec_repo: Optional[CanonicalWorkflowRepository] = None,
        plan_repo: Optional[ExecutionPlanRepository] = None,
        exec_repo: Optional[ExecutionRepository] = None,
        planner: Optional[ExecutionPlanner] = None,
        engine: Optional[ExecutionEngine] = None,
        verification_engine: Optional[object] = None,
        learning_engine: Optional[object] = None,
        gmail_client: Optional[GmailApiClient] = None,
    ) -> None:
        self.repo = repo or AutomationRepository()
        self.spec_repo = spec_repo or CanonicalWorkflowRepository()
        self.plan_repo = plan_repo or ExecutionPlanRepository()
        self.exec_repo = exec_repo or ExecutionRepository()
        self.planner = planner or ExecutionPlanner()
        self.engine = engine or ExecutionEngine(
            canonical_repo=self.spec_repo, plan_repo=self.plan_repo, exec_repo=self.exec_repo
        )
        if verification_engine is None:
            from app.services.verification_engine import VerificationEngine

            verification_engine = VerificationEngine(exec_repo=self.exec_repo, plan_repo=self.plan_repo)
        if learning_engine is None:
            from app.repositories.learning_repository import LearningRepository
            from app.services.learning_engine import LearningEngine

            learning_engine = LearningEngine(
                execution_repo=self.exec_repo,
                verification_repo=verification_engine.verif_repo,
                learning_repo=LearningRepository(),
                canonical_repo=self.spec_repo,
            )
        self.verification_engine = verification_engine
        self.learning_engine = learning_engine
        self.gmail = gmail_client or GmailApiClient()

    # ------------------------------------------------------------------ triggers

    def create_trigger(self, req: CreateTriggerRequest) -> EmailTrigger:
        spec = self.spec_repo.get_by_id(req.workflow_id)
        if not spec:
            raise TriggerError(f"Workflow '{req.workflow_id}' not found.")
        if spec.approval_state.state != ApprovalState.APPROVED:
            raise TriggerError(
                f"Workflow '{req.workflow_id}' is {spec.approval_state.state.value}; only approved workflows can be automated."
            )
        if not any(s.catalog_action == GMAIL_TRIGGER_ACTION for s in spec.steps):
            raise TriggerError(
                f"Workflow '{req.workflow_id}' has no '{GMAIL_TRIGGER_ACTION}' step, so an email cannot start it."
            )
        trigger = EmailTrigger(
            workflow_id=req.workflow_id,
            name=(req.name or "").strip() or f"{spec.title} · email trigger",
            gmail_query=req.gmail_query.strip(),
            poll_interval_seconds=req.poll_interval_seconds,
        )
        if req.include_existing_since is not None:
            trigger.active_since = int(req.include_existing_since)
        return self.repo.save_trigger(trigger)

    def update_trigger(self, trigger_id: str, req: UpdateTriggerRequest) -> EmailTrigger:
        trigger = self._require_trigger(trigger_id)
        if req.enabled is not None:
            trigger.enabled = req.enabled
        if req.gmail_query is not None:
            trigger.gmail_query = req.gmail_query.strip()
        if req.poll_interval_seconds is not None:
            trigger.poll_interval_seconds = req.poll_interval_seconds
        return self.repo.save_trigger(trigger)

    def _require_trigger(self, trigger_id: str) -> EmailTrigger:
        trigger = self.repo.get_trigger(trigger_id)
        if not trigger:
            raise LookupError(f"Trigger '{trigger_id}' not found.")
        return trigger

    # ------------------------------------------------------------------- polling

    def poll(self, trigger_id: str) -> PollResult:
        """Check Gmail once for this trigger and queue a pending run per new message."""
        trigger = self._require_trigger(trigger_id)
        now = datetime.now(timezone.utc).isoformat()
        result = PollResult(trigger_id=trigger.trigger_id, polled_at=now)

        error: Optional[str] = None
        if not self.gmail.is_configured():
            error = "Gmail is not set up. Connect Gmail in Settings."
        elif not self.gmail.is_authenticated():
            error = "Gmail is not connected yet. Use Connect Gmail in Settings."
        else:
            try:
                self._sync(trigger, result)
            except Exception as e:  # noqa: BLE001 - recorded on the trigger, never raised to the poller
                logger.warning("Trigger %s poll failed: %s", trigger.trigger_id, e)
                error = f"Gmail search failed: {e}"

        trigger.last_polled_at = now
        trigger.last_error = error
        trigger.last_note = result.note
        self.repo.save_trigger(trigger)
        result.error = error
        if result.new_runs:
            logger.info("Trigger %s queued %d run(s) for approval", trigger.trigger_id, len(result.new_runs))
        return result

    def _sync(self, trigger: EmailTrigger, result: PollResult) -> None:
        """One incremental sync step; updates `trigger`'s sync position only once nothing is left behind."""
        started = int(time.time())
        if trigger.history_id:
            try:
                added, latest = self.gmail.messages_added_since(trigger.history_id)
            except GmailHistoryExpired:
                result.note = "Gmail's change history had expired, so every email since the last check was searched."
            else:
                if not added:
                    trigger.history_id = latest
                    result.unchanged = True
                    return

        # Bookmark taken before listing: anything arriving during this poll is seen by the next one.
        bookmark = self.gmail.current_history_id()
        since = max(trigger.active_since, (trigger.synced_until or trigger.active_since) - SYNC_OVERLAP_SECONDS)
        ids = self.gmail.list_message_ids(query=f"({trigger.gmail_query}) after:{since}")
        result.matched = len(ids)

        # Gmail lists newest first; queue oldest first so runs appear in arrival order.
        new_ids = [mid for mid in reversed(ids) if not self.repo.has_message(trigger.trigger_id, mid)]
        batch = new_ids[:MAX_NEW_RUNS_PER_POLL]
        result.backlog = len(new_ids) - len(batch)
        for mid in batch:
            msg = self.gmail.get_message_summary(mid)
            run = WorkflowRun(
                trigger_id=trigger.trigger_id,
                workflow_id=trigger.workflow_id,
                gmail_query=trigger.gmail_query,
                source_email=SourceEmail(
                    message_id=msg.message_id,
                    thread_id=msg.thread_id,
                    subject=msg.subject,
                    sender=msg.sender,
                    snippet=msg.snippet,
                    received_at=msg.timestamp,
                    attachment_names=[a.filename for a in msg.attachments],
                ),
            )
            if self.repo.insert_run_if_new(run):
                result.new_runs.append(run)

        if result.backlog:
            result.note = f"{result.backlog} more matching email(s) will be queued by the next check."
        else:
            # Everything up to now is processed: move the sync position forward.
            trigger.synced_until = started
            trigger.history_id = bookmark

    def poll_due(self) -> List[PollResult]:
        """Poll every enabled trigger whose interval has elapsed (called by the background scheduler)."""
        now = datetime.now(timezone.utc)
        results: List[PollResult] = []
        for trigger in self.repo.list_triggers(enabled_only=True):
            if trigger.last_polled_at:
                elapsed = (now - datetime.fromisoformat(trigger.last_polled_at)).total_seconds()
                if elapsed < trigger.poll_interval_seconds:
                    continue
            results.append(self.poll(trigger.trigger_id))
        return results

    # ---------------------------------------------------------------------- runs

    def approve_run(self, run_id: str, decided_by: str) -> WorkflowRun:
        """Human approval of one run: plan it for this exact email and execute it live."""
        self.claim_for_approval(run_id, decided_by)
        return self.execute_claimed_run(run_id, decided_by)

    def claim_for_approval(self, run_id: str, decided_by: str) -> WorkflowRun:
        """Atomically move PENDING_APPROVAL -> RUNNING. Stops a double-click from running twice."""
        self._require_run(run_id)
        run = self.repo.transition_run(run_id, [RunStatus.PENDING_APPROVAL], RunStatus.RUNNING, decided_by)
        if run is None:
            raise TriggerError(f"Run '{run_id}' is no longer awaiting approval.")
        return run

    def execute_claimed_run(
        self, run_id: str, decided_by: str, before_execute: Optional[Callable[[], None]] = None
    ) -> WorkflowRun:
        """Plan and execute a run already claimed by claim_for_approval (called by the worker).

        `before_execute` runs right before the first step that may change external systems.
        """
        run = self._require_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise TriggerError(f"Run '{run_id}' is {run.status.value}, not approved for execution.")

        try:
            spec = self.spec_repo.get_by_id(run.workflow_id)
            if not spec:
                raise TriggerError(f"Workflow '{run.workflow_id}' no longer exists.")
            plan = self.planner.create_execution_plan(
                spec=spec,
                runtime_inputs={
                    "search_query": run.gmail_query,
                    "trigger_message_id": run.source_email.message_id,
                },
            )
            self.plan_repo.save(plan)
            run.execution_plan_id = plan.execution_plan_id
            self.repo.save_run(run)

            if before_execute:
                before_execute()
            record = self.engine.execute_plan(
                execution_plan_id=plan.execution_plan_id,
                idempotency_key=f"workflow-run:{run.run_id}",
                execution_mode=ExecutionMode.LIVE,
                executed_by=decided_by,
            )
        except Exception as e:  # noqa: BLE001 - the run must never be left stuck in RUNNING
            logger.warning("Run %s could not execute: %s", run_id, e)
            run.status = RunStatus.FAILED
            run.error = str(e)
            return self.repo.save_run(run)

        return self._sync_from_execution(run, record)

    def resume_run(self, run_id: str, inputs: Dict[str, str], decided_by: str) -> WorkflowRun:
        """Continue a paused run with the value a person supplied."""
        self.claim_for_resume(run_id, decided_by)
        return self.continue_claimed_run(run_id, inputs, decided_by)

    def claim_for_resume(self, run_id: str, decided_by: str) -> WorkflowRun:
        """Atomically move NEEDS_INPUT -> RUNNING."""
        self._require_run(run_id)
        run = self.repo.transition_run(run_id, [RunStatus.NEEDS_INPUT], RunStatus.RUNNING, decided_by)
        if run is None:
            raise TriggerError(f"Run '{run_id}' is not waiting for input.")
        return run

    def continue_claimed_run(
        self,
        run_id: str,
        inputs: Dict[str, str],
        decided_by: str,
        before_execute: Optional[Callable[[], None]] = None,
    ) -> WorkflowRun:
        """Resume a run claimed by claim_for_resume (called by the worker)."""
        run = self._require_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise TriggerError(f"Run '{run_id}' is {run.status.value}, not resumed.")
        try:
            if before_execute:
                before_execute()
            record = self.engine.resume_execution(run.execution_id or "", inputs, resumed_by=decided_by)
        except ValueError as e:
            # Invalid input: put the run back so the person can try again.
            run.status = RunStatus.NEEDS_INPUT
            run.error = f"Input not accepted: {e}"
            self.repo.save_run(run)
            raise TriggerError(str(e)) from e
        except Exception as e:  # noqa: BLE001
            run.status = RunStatus.FAILED
            run.error = str(e)
            return self.repo.save_run(run)
        return self._sync_from_execution(run, record)

    def reject_run(self, run_id: str, decided_by: str) -> WorkflowRun:
        """Discard a run that is awaiting approval or input. A paused execution is cancelled."""
        self._require_run(run_id)
        run = self.repo.transition_run(
            run_id, [RunStatus.PENDING_APPROVAL, RunStatus.NEEDS_INPUT], RunStatus.REJECTED, decided_by
        )
        if run is None:
            raise TriggerError(f"Run '{run_id}' can no longer be rejected.")
        if run.execution_id:
            record = self.exec_repo.get_by_id(run.execution_id)
            if record and record.status == ExecutionOverallStatus.NEEDS_INPUT:
                record.status = ExecutionOverallStatus.CANCELLED
                record.error_summary = f"Cancelled by {decided_by} while waiting for input."
                record.end_time = datetime.now(timezone.utc).isoformat()
                self.exec_repo.save(record)
        run.intervention = None
        return self.repo.save_run(run)

    def mark_interrupted(self, run_id: str, reason: str) -> Optional[WorkflowRun]:
        """The worker stopped mid-run after external changes may have happened: a person must check."""
        run = self.repo.get_run(run_id)
        if run is None or run.status != RunStatus.RUNNING:
            return run
        run.status = RunStatus.NEEDS_ATTENTION
        run.error = reason
        return self.repo.save_run(run)

    def _require_run(self, run_id: str) -> WorkflowRun:
        run = self.repo.get_run(run_id)
        if not run:
            raise LookupError(f"Run '{run_id}' not found.")
        return run

    def _sync_from_execution(self, run: WorkflowRun, record: ExecutionAuditRecord) -> WorkflowRun:
        run.execution_id = record.execution_id
        run.status = _RUN_STATUS_FROM_EXECUTION.get(record.status, RunStatus.FAILED)
        run.error = None if run.status in (RunStatus.COMPLETED, RunStatus.NEEDS_INPUT) else record.error_summary
        run.intervention = None
        if run.status == RunStatus.NEEDS_INPUT:
            paused = next(
                (s for s in reversed(record.step_results) if s.status == ExecutionStepStatus.NEEDS_INPUT), None
            )
            run.intervention = {
                **((paused.intervention if paused else None) or {}),
                "step": paused.action_name if paused else None,
            }

        if run.status != RunStatus.NEEDS_INPUT:
            run.verification_status = self._verify_and_learn(run, record)
        return self.repo.save_run(run)

    def _verify_and_learn(self, run: WorkflowRun, record: ExecutionAuditRecord) -> Optional[str]:
        """Independent verification and reliability analysis; failures here never change the run outcome."""
        status: Optional[str] = None
        try:
            verification = self.verification_engine.verify_execution(record.execution_id, force_recheck=True)
            status = verification.overall_status.value
        except Exception as e:  # noqa: BLE001
            logger.warning("Verification for run %s failed: %s", run.run_id, e)
        try:
            self.learning_engine.analyze_workflow(run.workflow_id, persist=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Learning update for run %s failed: %s", run.run_id, e)
        return status
