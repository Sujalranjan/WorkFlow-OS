"""files.save_to_folder: safe names, folder checks, executor, verifier, Settings, observation, and a
discovered Gmail -> shared folder -> Slack workflow run end to end against a temp folder."""

import os
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app import config
from app.integrations.files import SAVE_TO_FOLDER, classify_save
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionContext, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.verification import VerificationStatus
from app.services import integrations as integrations_module
from app.services import shared_folder
from app.services.credential_store import SHARED_FOLDER, CredentialStore, set_credential_store
from app.services.executors.folder_executor import SharedFolderExecutor
from app.services.verifiers.folder_verifier import SharedFolderVerificationStrategy


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("SHARED_FOLDER_PATH", raising=False)
    s = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    set_credential_store(s)
    yield s
    set_credential_store(None)


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "shared"
    d.mkdir()
    return d


@pytest.fixture
def sandbox(tmp_path):
    d = tmp_path / "sandbox-run"
    d.mkdir()
    (d / "invoice_101.pdf").write_bytes(b"%PDF-1.4 invoice 101")
    return d


def _step(params=None):
    from app.models.canonical import RiskCategory, RiskLevel, StepRisk
    from app.models.execution_plan import ExecutionStrategy, ExpectedStateChange, PlannedStep, StepExecutionStrategy

    return PlannedStep(
        plan_step_id="plan-save",
        source_canonical_step_id="c",
        source_semantic_step_id="s",
        source_dna_step_key="files:save_to_folder",
        application="Files",
        action="save_to_folder",
        description="save",
        resolved_parameters=params or {},
        execution_strategy=StepExecutionStrategy(strategy=ExecutionStrategy.API, reason="t", target_technology="Files"),
        risk=StepRisk(step_id="c", application="Files", action="save_to_folder", risk_level=RiskLevel.MEDIUM,
                      risk_category=RiskCategory.LOCAL_CHANGE, reason="t"),
        expected_result="",
        evidence_reference="",
        state_change=ExpectedStateChange(target_system="Files", entity_or_property="file", before_state="", expected_after_state=""),
        catalog_action="files.save_to_folder",
    )


def _ctx(sandbox, dry_run=False, **params):
    return ExecutionContext(
        execution_id="exec-fs", workflow_id="wf", execution_plan_id="plan", sandbox_root=str(sandbox),
        execution_mode=ExecutionMode.DRY_RUN if dry_run else ExecutionMode.LIVE, dry_run=dry_run, resolved_parameters=params,
    )


# ------------------------------------------------------------- safety rules


@pytest.mark.parametrize(
    "given, expected",
    [
        ("invoice.pdf", "invoice.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\Windows\\win.ini", "win.ini"),
        ('bad:na*me?.pdf', "bad_na_me_.pdf"),
        (".hidden", "hidden"),
        ("report. ", "report"),
        ("CON.txt", "_CON.txt"),
        ("", "file"),
        ("a" * 300 + ".pdf", "a" * 176 + ".pdf"),
    ],
)
def test_safe_file_name(given, expected):
    assert shared_folder.safe_file_name(given) == expected


def test_check_folder_rejects_unsafe_choices(tmp_path, folder):
    assert shared_folder.check_folder(str(folder)) == folder.resolve()
    for bad in ("relative/folder", str(tmp_path / "missing")):
        with pytest.raises(shared_folder.FolderUnavailable):
            shared_folder.check_folder(bad)
    with pytest.raises(shared_folder.NotConfigured):
        shared_folder.check_folder("")
    # WorkFlowOS's own data and sandbox folders (and anything containing them) are off limits
    for protected in (Path(config.SANDBOX_DIR), Path(config.secret_key_path()).parent, Path(config.SANDBOX_DIR).parent):
        protected.mkdir(parents=True, exist_ok=True)
        with pytest.raises(shared_folder.FolderUnavailable, match="outside WorkFlowOS"):
            shared_folder.check_folder(str(protected.resolve()))


# ----------------------------------------------------------------- executor


def test_save_copies_once_never_overwrites_and_verifies(store, folder, sandbox):
    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    (folder / "invoice_101.pdf").write_bytes(b"someone else's file")
    ex, checker = SharedFolderExecutor(), SharedFolderVerificationStrategy()

    res = ex.execute(_step({"source_file": "{downloaded_file}", "file_name": "{filename}"}),
                     _ctx(sandbox, downloaded_file=str(sandbox / "invoice_101.pdf"), filename="invoice_101.pdf"))
    assert res.status == ExecutionStepStatus.SUCCESS, res.error
    assert res.output["file_name"] == "invoice_101 (2).pdf" and res.output["renamed"] is True
    assert (folder / "invoice_101.pdf").read_bytes() == b"someone else's file"  # untouched
    assert (folder / "invoice_101 (2).pdf").read_bytes() == b"%PDF-1.4 invoice 101"

    [check] = checker.build_checks("exec-fs", _step(), res, str(sandbox))
    assert checker.verify(check, str(sandbox)).status == VerificationStatus.VERIFIED
    (folder / "invoice_101 (2).pdf").write_bytes(b"tampered")
    [check] = checker.build_checks("exec-fs", _step(), res, str(sandbox))
    assert checker.verify(check, str(sandbox)).status == VerificationStatus.FAILED


def test_names_from_a_run_cannot_escape_the_folder(store, folder, sandbox, tmp_path):
    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    res = SharedFolderExecutor().execute(_step({"file_name": "../../escaped.pdf"}),
                                         _ctx(sandbox, downloaded_file=str(sandbox / "invoice_101.pdf")))
    assert res.status == ExecutionStepStatus.SUCCESS
    assert Path(res.output["saved_path"]).parent == folder.resolve() and not (tmp_path / "escaped.pdf").exists()


def test_only_the_runs_own_file_can_be_copied(store, folder, sandbox, tmp_path):
    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    secret = tmp_path / "server-secret.txt"
    secret.write_text("x")
    ex = SharedFolderExecutor()
    outside = ex.execute(_step({"source_file": str(secret)}), _ctx(sandbox))
    assert outside.status == ExecutionStepStatus.BLOCKED and outside.blocked_reason == "INVALID_PARAMETER"
    sneaky = ex.execute(_step({"source_file": str(sandbox / ".." / "server-secret.txt")}), _ctx(sandbox))
    assert sneaky.status == ExecutionStepStatus.BLOCKED
    missing = ex.execute(_step(), _ctx(sandbox))  # nothing downloaded upstream
    assert missing.status == ExecutionStepStatus.BLOCKED
    assert os.listdir(folder) == []


def test_unconfigured_missing_folder_and_dry_run(store, folder, sandbox):
    ex = SharedFolderExecutor()
    ctx = _ctx(sandbox, downloaded_file=str(sandbox / "invoice_101.pdf"))
    none = ex.execute(_step(), ctx)
    assert none.status == ExecutionStepStatus.BLOCKED and none.blocked_reason == "NOT_CONFIGURED"

    store.put(SHARED_FOLDER, {}, {"folder": str(folder / "was-removed")})
    gone = ex.execute(_step(), ctx)
    assert gone.status == ExecutionStepStatus.BLOCKED and gone.blocked_reason == "INTEGRATION_UNAVAILABLE"

    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    dry = ex.execute(_step(), _ctx(sandbox, dry_run=True, filename="invoice_101.pdf"))
    assert dry.status == ExecutionStepStatus.SUCCESS and dry.output["status"] == "SIMULATED"
    assert dry.output["file_name"] == "invoice_101.pdf" and os.listdir(folder) == []


def test_environment_fallback(store, folder, monkeypatch):
    monkeypatch.setenv("SHARED_FOLDER_PATH", str(folder))
    assert shared_folder.configured_folder() == (str(folder), "environment")
    assert shared_folder.folder_status() == (True, "Shared folder ready")


# -------------------------------------------------------------- observation


def test_only_files_in_the_watched_shared_folder_count():
    shared = ActivityEvent(event_type=ActivityEventType.FILE_CREATED, application="File System",
                           metadata={"file_name": "inv.pdf", "file_path": "S:/Team/inv.pdf", "folder_role": "shared"})
    assert classify_save(shared).action == SAVE_TO_FOLDER and classify_save(shared).parameters == {"file_name": "inv.pdf"}
    moved = ActivityEvent(event_type=ActivityEventType.FILE_MOVED, application="File System",
                          metadata={"file_name": "inv.pdf", "folder_role": "shared"})
    assert classify_save(moved) is not None
    # ordinary file events (the watch folder, the demo's generated reports, downloads) are not this action
    for evt in (
        ActivityEvent(event_type=ActivityEventType.FILE_CREATED, application="File System", metadata={"file_name": "report.json"}),
        ActivityEvent(event_type=ActivityEventType.FILE_DOWNLOADED, application="File System",
                      metadata={"file_name": "a.pdf", "folder_role": "shared"}),
    ):
        assert classify_save(evt) is None


def test_desktop_agent_tags_the_shared_folder(tmp_path, monkeypatch):
    from desktop_agent.agent import DesktopAgent
    from desktop_agent.collectors.file_collector import FileSystemCollector

    assert FileSystemCollector(watch_directory=str(tmp_path)).role_metadata() == {}
    monkeypatch.setenv("SHARED_FOLDER_DIRECTORY", str(tmp_path / "shared"))
    agent = DesktopAgent(enable_real_collection=True, watch_directory=str(tmp_path / "watch"))
    assert agent.shared_folder_collector.role_metadata() == {"folder_role": "shared"}
    assert agent.shared_folder_collector.watch_directory == os.path.abspath(str(tmp_path / "shared"))
    monkeypatch.delenv("SHARED_FOLDER_DIRECTORY")
    assert DesktopAgent(enable_real_collection=True, watch_directory=str(tmp_path / "watch")).shared_folder_collector is None


# ----------------------------------------------------------------- settings


def test_settings_choose_and_clear_the_folder(store, folder, monkeypatch):
    svc = integrations_module.IntegrationService(store=store)
    monkeypatch.setattr(integrations_module, "_service", svc)
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/api/integrations").json()["files"]["configured"] is False
    bad = client.put("/api/integrations/files", json={"folder": "relative/path"})
    assert bad.status_code == 400 and "full path" in bad.json()["detail"]
    ok = client.put("/api/integrations/files", json={"folder": str(folder)})
    files = ok.json()["files"]
    assert files["configured"] and files["ready"] and files["folder"] == str(folder.resolve()) and files["source"] == "settings"
    assert client.delete("/api/integrations/files").json()["files"]["configured"] is False


# ------------------------------------------- discovered workflow, end to end


def test_discovered_gmail_folder_slack_workflow_runs(tmp_path, store, folder):
    from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
    from app.models.slack import SlackNotificationResult
    from app.repositories.canonical_repository import CanonicalWorkflowRepository
    from app.repositories.execution_plan_repository import ExecutionPlanRepository
    from app.repositories.execution_repository import ExecutionRepository
    from app.repositories.learning_repository import LearningRepository
    from app.repositories.verification_repository import VerificationRepository
    from app.services.canonical_factory import CanonicalWorkflowFactory
    from app.services.execution_engine import ExecutionEngine
    from app.services.execution_planner import ExecutionPlanner
    from app.services.executors.gmail_executor import GmailApiExecutor
    from app.services.executors.slack_executor import SlackApiExecutor
    from app.services.gmail_client import GmailApiClient
    from app.services.learning_engine import LearningEngine
    from app.services.observed_sessions import GMAIL_SEARCH, SLACK_CHANNEL, build_observed_folder_events
    from app.services.reference_workflow import WorkflowOrchestrator
    from app.services.semantic_engine import SemanticUnderstandingEngine
    from app.services.semantic_provider import MockSemanticProvider
    from app.services.slack_client import SlackApiClient
    from app.services.verification_engine import VerificationEngine
    from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
    from app.services.verifiers.slack_verifier import SlackVerificationStrategy
    from app.services.workflow_discovery import WorkflowDiscoveryEngine
    from app.services.workflow_dna_extractor import WorkflowDNAExtractor
    from app.services.workflow_segmenter import WorkflowSegmenter

    sessions = WorkflowSegmenter().segment(build_observed_folder_events())
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    assert [s.catalog_action for s in dna.invariant_steps if s.catalog_action] == [
        "gmail.search_email", "gmail.download_attachment", "files.save_to_folder", "slack.send_notification",
    ]
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert semantic.status == "success", semantic.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)

    db = str(tmp_path / "fs.db")
    repos = dict(canonical_repo=CanonicalWorkflowRepository(db), plan_repo=ExecutionPlanRepository(db), exec_repo=ExecutionRepository(db))
    verif_repo, learn_repo = VerificationRepository(db), LearningRepository(db)
    engine = ExecutionEngine(**repos, default_sandbox_base=str(tmp_path / "sandbox"))
    orch = WorkflowOrchestrator(
        **repos, verif_repo=verif_repo, learning_repo=learn_repo, engine=engine, planner=ExecutionPlanner(),
        verification_engine=VerificationEngine(exec_repo=repos["exec_repo"], plan_repo=repos["plan_repo"], verif_repo=verif_repo),
        learning_engine=LearningEngine(execution_repo=repos["exec_repo"], verification_repo=verif_repo, learning_repo=learn_repo),
    )
    orch.canonical_repo.save(spec)
    orch.approve_workflow(spec.workflow_id)
    plan = orch.create_plan(spec.workflow_id)
    [save] = [s for s in plan.planned_steps if s.catalog_action == "files.save_to_folder"]
    # the file name changed between recordings, so it comes from this run's download, never a past one
    assert save.resolved_parameters == {"source_file": "{downloaded_file}", "file_name": "{filename}"}

    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    gmail = MagicMock(spec=GmailApiClient)
    gmail.is_configured.return_value = gmail.is_authenticated.return_value = True
    gmail.search_messages.return_value = GmailSearchResult(
        query=GMAIL_SEARCH, total_found=1,
        messages=[GmailMessageSummary(
            message_id="msg-new", thread_id="t", subject="Replacement request", sender="Asha <asha@example.com>",
            has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="a1", filename="invoice_777.pdf", size_bytes=10)],
        )],
    )
    gmail.download_attachment.return_value = (b"%PDF-1.4 new invoice", {"filename": "invoice_777.pdf", "mime_type": "application/pdf"})
    slack = MagicMock(spec=SlackApiClient)
    slack.default_channel_id = SLACK_CHANNEL
    slack.send_notification.return_value = SlackNotificationResult(success=True, channel=SLACK_CHANNEL, ts="1.2")
    slack.verify_message.return_value = (True, {"ts": "1.2"}, "found")
    for ex in (GmailApiExecutor(client=gmail), SlackApiExecutor(client=slack)):
        orch.engine.registry.register(ex)
    for v in (GmailVerificationStrategy(), SlackVerificationStrategy(client=slack)):
        orch.verification_engine.strategy_registry.register(v)

    record = orch.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    assert os.listdir(folder) == ["invoice_777.pdf"]
    assert (folder / "invoice_777.pdf").read_bytes() == b"%PDF-1.4 new invoice"

    verification = orch.verify_execution(record.execution_id)
    [check] = [c for c in verification.checks if c.check_type == "shared_folder_file_saved"]
    assert check.status == VerificationStatus.VERIFIED
