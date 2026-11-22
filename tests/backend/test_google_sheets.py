"""sheets.append_row: opt-in permission, configured sheet only, RAW values, executor/verifier,
Settings, observation, and a discovered Gmail -> sheet -> Slack routine run against a fake Sheets API."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app import config
from app.integrations.google_sheets import APPEND_ROW, classify_open_sheet
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionContext, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.verification import VerificationStatus
from app.services import google_sheets
from app.services import integrations as integrations_module
from app.services.credential_store import GMAIL_OPTIONS, GMAIL_TOKEN, SHEETS, CredentialStore, set_credential_store
from app.services.executors.sheets_executor import GoogleSheetsExecutor
from app.services.verifiers.sheets_verifier import GoogleSheetsVerificationStrategy

READONLY, SHEETS_SCOPE = config.GMAIL_SCOPES[0], config.SHEETS_SCOPE
SHEET_ID = "1WfOsLogSheet0000000000000000000000000000ab"


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeSheets:
    """spreadsheets().get, spreadsheets().values().append / get over in-memory tabs."""

    def __init__(self):
        self.tabs = {"Log": [["Date", "Subject", "From", "File"]], "Other": []}
        self.appends = []

    def spreadsheets(self):
        return self

    def values(self):
        return _Values(self)

    def get(self, spreadsheetId, fields):
        if spreadsheetId != SHEET_ID:
            raise _HttpError(404)
        return _Call(lambda: {"properties": {"title": "Ops log"}, "sheets": [{"properties": {"title": t}} for t in self.tabs]})


class _HttpError(Exception):
    def __init__(self, status):
        self.resp = type("Resp", (), {"status": status})()


class _Values:
    def __init__(self, fake):
        self.fake = fake

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        def run():
            assert valueInputOption == "RAW" and insertDataOption == "INSERT_ROWS"  # never formulas, never overwrite
            tab = range.split("!")[0].strip("'").replace("''", "'")
            rows = self.fake.tabs[tab]
            rows.extend(body["values"])
            self.fake.appends.append((tab, body["values"]))
            n, width = len(rows), len(body["values"][0])
            return {"updates": {"updatedRange": f"'{tab}'!A{n}:{chr(64 + width)}{n}"}}

        return _Call(run)

    def get(self, spreadsheetId, range, valueRenderOption):
        def run():
            tab, cells = range.split("!")
            row_no = int(cells.split(":")[0][1:])
            return {"values": [self.fake.tabs[tab.strip("'")][row_no - 1]]}

        return _Call(run)


@pytest.fixture
def sheets():
    return FakeSheets()


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    set_credential_store(s)
    yield s
    set_credential_store(None)


def _allow(store, granted=(READONLY, SHEETS_SCOPE), opted_in=True):
    store.put(GMAIL_OPTIONS, {}, {"allow_sheets": opted_in})
    store.put(GMAIL_TOKEN, {"refresh_token": "r"}, {"account": "ops@example.com", "scopes": list(granted)})


def _configure(store, columns=("date", "email_subject", "customer_email", "filename")):
    store.put(SHEETS, {}, {"spreadsheet_id": SHEET_ID, "title": "Ops log", "sheet": "Log", "columns": list(columns)})


def _step(params=None):
    from app.models.canonical import RiskCategory, RiskLevel, StepRisk
    from app.models.execution_plan import ExecutionStrategy, ExpectedStateChange, PlannedStep, StepExecutionStrategy

    return PlannedStep(
        plan_step_id="plan-row",
        source_canonical_step_id="c",
        source_semantic_step_id="s",
        source_dna_step_key="google sheets:append_row",
        application="Google Sheets",
        action="append_row",
        description="row",
        resolved_parameters=params or {},
        execution_strategy=StepExecutionStrategy(strategy=ExecutionStrategy.API, reason="t", target_technology="Sheets"),
        risk=StepRisk(step_id="c", application="Google Sheets", action="append_row", risk_level=RiskLevel.MEDIUM,
                      risk_category=RiskCategory.EXTERNAL_CHANGE, reason="t"),
        expected_result="",
        evidence_reference="",
        state_change=ExpectedStateChange(target_system="Sheets", entity_or_property="row", before_state="", expected_after_state=""),
        catalog_action="sheets.append_row",
    )


def _ctx(tmp_path, dry_run=False, **params):
    return ExecutionContext(
        execution_id="exec-sh", workflow_id="wf-sh", execution_plan_id="plan", sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.DRY_RUN if dry_run else ExecutionMode.LIVE, dry_run=dry_run, resolved_parameters=params,
    )


# ------------------------------------------------------------------ helpers


def test_parse_spreadsheet_id_and_rows():
    assert google_sheets.parse_spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0") == SHEET_ID
    assert google_sheets.parse_spreadsheet_id(SHEET_ID) == SHEET_ID
    assert google_sheets.parse_spreadsheet_id("https://example.com/x") is None
    assert google_sheets.a1_tab("It's") == "'It''s'"
    row = google_sheets.build_row(
        ["date", "email_subject", "customer_name", "filename"],
        {"email_subject": "=IMPORTXML(\"http://x\")", "customer_name": "{customer_name}", "filename": "a.pdf"},
        now=datetime(2026, 11, 23, 9, 30, tzinfo=timezone.utc),
    )
    # an unfilled template is left empty; formula-looking text is kept as text (written RAW)
    assert row == ["2026-11-23 09:30:00 UTC", "=IMPORTXML(\"http://x\")", "", "a.pdf"]


def test_permission_states(store):
    assert "Google Sheets is off" in google_sheets.sheets_status()
    _allow(store, granted=(READONLY,))
    assert "Reconnect Gmail" in google_sheets.sheets_status()
    _allow(store)
    assert google_sheets.sheets_status() is None


# ----------------------------------------------------------------- executor


def test_appends_one_row_to_the_configured_sheet_and_verifies(store, sheets, tmp_path):
    _allow(store)
    _configure(store)
    client = google_sheets.GoogleSheetsClient(service=sheets)
    ex, checker = GoogleSheetsExecutor(client=client), GoogleSheetsVerificationStrategy(client=client)
    res = ex.execute(_step({"spreadsheet_id": SHEET_ID}),
                     _ctx(tmp_path, email_subject="Replacement request", customer_email="asha@example.com", filename="i.pdf"))
    assert res.status == ExecutionStepStatus.SUCCESS, res.error
    [(tab, [row])] = sheets.appends
    assert tab == "Log" and row[1:] == ["Replacement request", "asha@example.com", "i.pdf"]
    assert sheets.tabs["Log"][0] == ["Date", "Subject", "From", "File"]  # existing rows untouched
    assert res.output["updated_range"] == "'Log'!A2:D2"

    [check] = checker.build_checks("exec-sh", _step(), res, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.VERIFIED
    sheets.tabs["Log"][1] = ["edited", "by", "someone", "else"]
    [check] = checker.build_checks("exec-sh", _step(), res, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.FAILED


def test_never_writes_anywhere_but_the_configured_sheet(store, sheets, tmp_path):
    _allow(store)
    ex = GoogleSheetsExecutor(client=google_sheets.GoogleSheetsClient(service=sheets))
    unset = ex.execute(_step(), _ctx(tmp_path))
    assert unset.status == ExecutionStepStatus.BLOCKED and unset.blocked_reason == "NOT_CONFIGURED"
    _configure(store)
    other = ex.execute(_step({"spreadsheet_id": "1SomeoneElsesSheet000000000000000000000000"}), _ctx(tmp_path))
    assert other.status == ExecutionStepStatus.BLOCKED and "another spreadsheet" in other.error
    assert sheets.appends == []


def test_blocked_without_permission_and_dry_run_makes_no_calls(store, sheets, tmp_path):
    _configure(store)
    ex = GoogleSheetsExecutor(client=google_sheets.GoogleSheetsClient(service=sheets))
    refused = ex.execute(_step(), _ctx(tmp_path))
    assert refused.status == ExecutionStepStatus.BLOCKED and refused.blocked_reason == "MISSING_SCOPE"
    dry = ex.execute(_step(), _ctx(tmp_path, dry_run=True, email_subject="s"))
    assert dry.status == ExecutionStepStatus.SUCCESS and dry.output["status"] == "SIMULATED" and dry.output["row"][1] == "s"
    assert sheets.appends == []


# -------------------------------------------------------------- observation


def test_opening_a_sheet_is_recognised():
    open_sheet = ActivityEvent(event_type=ActivityEventType.BROWSER_NAVIGATION,
                               metadata={"url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"})
    assert classify_open_sheet(open_sheet).action == APPEND_ROW
    assert classify_open_sheet(open_sheet).parameters == {"spreadsheet_id": SHEET_ID}
    for url in (f"https://docs.google.com/document/d/{SHEET_ID}/edit", f"https://docs.google.com.evil.example/spreadsheets/d/{SHEET_ID}"):
        assert classify_open_sheet(ActivityEvent(event_type=ActivityEventType.BROWSER_NAVIGATION, metadata={"url": url})) is None


# ----------------------------------------------------------------- settings


def test_settings_choose_sheet_tab_and_columns(store, sheets, monkeypatch):
    _allow(store)
    svc = integrations_module.IntegrationService(store=store)
    real = google_sheets.GoogleSheetsClient
    monkeypatch.setattr(integrations_module, "_service", svc)
    monkeypatch.setattr(google_sheets, "GoogleSheetsClient", lambda: real(service=sheets))  # Settings checks with the fake
    from app.main import create_app

    client = TestClient(create_app())
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    assert client.put("/api/integrations/sheets", json={"spreadsheet": "https://example.com/not-a-sheet", "columns": ["date"]}).status_code == 400
    bad_col = client.put("/api/integrations/sheets", json={"spreadsheet": url, "columns": ["date", "email_body"]})
    assert bad_col.status_code == 400 and "Choose columns from" in bad_col.json()["detail"]
    bad_tab = client.put("/api/integrations/sheets", json={"spreadsheet": url, "sheet": "Nope", "columns": ["date"]})
    assert bad_tab.status_code == 400 and "no tab named 'Nope'" in bad_tab.json()["detail"]
    missing = client.put("/api/integrations/sheets", json={"spreadsheet": "1NotThere000000000000000000000000", "columns": ["date"]})
    assert missing.status_code == 400

    ok = client.put("/api/integrations/sheets", json={"spreadsheet": url, "columns": ["date", "customer_email"]}).json()["sheets"]
    assert ok["configured"] and ok["title"] == "Ops log" and ok["sheet"] == "Log" and ok["columns"] == ["date", "customer_email"]
    assert "email_body" not in ok["available_columns"]

    options = client.put("/api/integrations/gmail/options", json={"allow_sheets": False}).json()["gmail"]
    assert options["sheets_allowed"] is False
    assert client.delete("/api/integrations/sheets").json()["sheets"]["configured"] is False


def test_options_are_independent(store):
    svc = integrations_module.IntegrationService(store=store)
    svc.set_gmail_options(True, "admin")
    svc.set_gmail_options(None, "admin", allow_sheets=True)
    assert svc.gmail_labels_allowed() and svc.gmail_sheets_allowed()
    assert svc._gmail_requested_scopes() == [READONLY, config.GMAIL_MODIFY_SCOPE, SHEETS_SCOPE]
    svc.set_gmail_options(False, "admin")
    assert svc._gmail_requested_scopes() == [READONLY, SHEETS_SCOPE]


# ------------------------------------------- discovered workflow, end to end


def test_discovered_gmail_sheet_slack_workflow_runs(tmp_path, store, sheets):
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
    from app.services.observed_sessions import GMAIL_SEARCH, LOG_SPREADSHEET_ID, SLACK_CHANNEL, build_observed_sheet_events
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

    assert LOG_SPREADSHEET_ID == SHEET_ID
    sessions = WorkflowSegmenter().segment(build_observed_sheet_events())
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    assert [s.catalog_action for s in dna.invariant_steps if s.catalog_action] == [
        "gmail.search_email", "gmail.download_attachment", "sheets.append_row", "slack.send_notification",
    ]
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert semantic.status == "success", semantic.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)

    db = str(tmp_path / "sh.db")
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
    [row_step] = [s for s in plan.planned_steps if s.catalog_action == "sheets.append_row"]
    assert row_step.resolved_parameters == {"spreadsheet_id": SHEET_ID}

    _allow(store)
    _configure(store, columns=("email_subject", "customer_email", "filename", "execution_id"))
    reader = MagicMock(spec=GmailApiClient)
    reader.is_configured.return_value = reader.is_authenticated.return_value = True
    reader.search_messages.return_value = GmailSearchResult(
        query=GMAIL_SEARCH, total_found=1,
        messages=[GmailMessageSummary(
            message_id="msg-sh", thread_id="t", subject="Replacement request", sender="Asha <asha@example.com>",
            has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="a1", filename="invoice_3.pdf", size_bytes=10)],
        )],
    )
    reader.download_attachment.return_value = (b"%PDF-1.4 3", {"filename": "invoice_3.pdf", "mime_type": "application/pdf"})
    slack = MagicMock(spec=SlackApiClient)
    slack.default_channel_id = SLACK_CHANNEL
    slack.send_notification.return_value = SlackNotificationResult(success=True, channel=SLACK_CHANNEL, ts="1.2")
    slack.verify_message.return_value = (True, {"ts": "1.2"}, "found")
    client = google_sheets.GoogleSheetsClient(service=sheets)
    for ex in (GmailApiExecutor(client=reader), GoogleSheetsExecutor(client=client), SlackApiExecutor(client=slack)):
        orch.engine.registry.register(ex)
    for v in (GmailVerificationStrategy(), GoogleSheetsVerificationStrategy(client=client), SlackVerificationStrategy(client=slack)):
        orch.verification_engine.strategy_registry.register(v)

    record = orch.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    assert sheets.tabs["Log"][1] == ["Replacement request", "asha@example.com", "invoice_3.pdf", record.execution_id]

    verification = orch.verify_execution(record.execution_id)
    [check] = [c for c in verification.checks if c.check_type == "sheets_row_appended"]
    assert check.status == VerificationStatus.VERIFIED
