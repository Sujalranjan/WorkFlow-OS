"""HubSpot: client, executor, verifier, Settings, observation rules, and a discovered Gmail -> HubSpot
-> Slack workflow, all against an in-memory fake of the HubSpot API (no real account needed)."""

import json
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from app.integrations.hubspot import ADD_NOTE, FIND_CONTACT, UPDATE_CONTACT, classify_change, classify_lookup
from app.models.event import ActivityEvent, ActivityEventType
from app.models.execution import ExecutionContext, ExecutionMode, ExecutionOverallStatus, ExecutionStepStatus
from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
from app.models.slack import SlackNotificationResult
from app.models.verification import VerificationStatus
from app.services import integrations as integrations_module
from app.services.credential_store import HUBSPOT, CredentialStore, set_credential_store
from app.services.executors.hubspot_executor import HubSpotApiExecutor
from app.services.hubspot_client import HubSpotClient, HubSpotError, HubSpotRateLimited
from app.services.verifiers.hubspot_verifier import HubSpotVerificationStrategy

TOKEN = "pat-na1-test-service-key-0000000000"


class FakeHubSpot:
    """In-memory contacts and notes behind HubSpot's documented REST paths."""

    def __init__(self):
        self.contacts = {
            "90001": {"email": "rahul.sharma@example.com", "firstname": "Rahul", "lastname": "Sharma", "company": "Acme", "replacement_status": "open"},
            "90002": {"email": "priya.patel@example.com", "firstname": "Priya", "lastname": "Patel", "company": "Globex", "replacement_status": "open"},
            "90003": {"email": "priya.p@example.com", "firstname": "Priya", "lastname": "P", "company": "Globex", "replacement_status": "open"},
        }
        self.notes = {}
        self.calls = []
        self.status_override = None
        self.scopes_missing_for_notes = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "invalid token"})
        if self.status_override:
            return httpx.Response(self.status_override, json={})
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}

        if path == "/account-info/v3/details":
            return httpx.Response(200, json={"portalId": 4812345, "uiDomain": "app.hubspot.com"})
        if path == "/crm/v3/objects/contacts" and method == "GET":
            return httpx.Response(200, json={"results": [self._out(i) for i in list(self.contacts)[:1]]})
        if path == "/crm/v3/objects/contacts/search":
            if "filterGroups" in body:
                email = body["filterGroups"][0]["filters"][0]["value"].lower()
                ids = [i for i, c in self.contacts.items() if c["email"].lower() == email]
            else:
                q = body["query"].lower()
                ids = [i for i, c in self.contacts.items() if q in " ".join(map(str, c.values())).lower()]
            return httpx.Response(200, json={"total": len(ids), "results": [self._out(i) for i in ids]})
        if path.startswith("/crm/v3/objects/contacts/"):
            cid = path.rsplit("/", 1)[-1]
            if cid not in self.contacts:
                return httpx.Response(404, json={})
            if method == "PATCH":
                self.contacts[cid].update(body["properties"])
            return httpx.Response(200, json=self._out(cid))
        if path == "/crm/v3/objects/notes" and method == "POST":
            if self.scopes_missing_for_notes:
                return httpx.Response(403, json={})
            assoc = body["associations"][0]
            assert assoc["types"] == [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
            note_id = str(70000 + len(self.notes))
            self.notes[note_id] = {"body": body["properties"]["hs_note_body"], "contact": assoc["to"]["id"]}
            return httpx.Response(201, json={"id": note_id, "properties": body["properties"]})
        if path.startswith("/crm/v3/objects/notes/"):
            note = self.notes.get(path.rsplit("/", 1)[-1])
            if note is None:
                return httpx.Response(404, json={})
            return httpx.Response(
                200,
                json={
                    "id": path.rsplit("/", 1)[-1],
                    "properties": {"hs_note_body": note["body"]},
                    "associations": {"contacts": {"results": [{"id": note["contact"], "type": "note_to_contact"}]}},
                },
            )
        if path == "/crm/v3/properties/contacts":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "replacement_status", "label": "Replacement status", "type": "enumeration",
                         "options": [{"value": "open"}, {"value": "processed"}]},
                        {"name": "jobtitle", "label": "Job title", "type": "string"},
                        {"name": "hs_object_id", "label": "Record ID", "type": "number", "modificationMetadata": {"readOnlyValue": True}},
                    ]
                },
            )
        return httpx.Response(404, json={})

    def _out(self, cid):
        return {"id": cid, "properties": dict(self.contacts[cid])}

    def http(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake():
    return FakeHubSpot()


@pytest.fixture
def client(fake):
    return HubSpotClient(access_token=TOKEN, http_client=fake.http())


@pytest.fixture
def store(tmp_path):
    s = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    set_credential_store(s)
    yield s
    set_credential_store(None)


def _step(action, params=None):
    from app.models.canonical import RiskCategory, RiskLevel, StepRisk
    from app.models.execution_plan import ExecutionStrategy, ExpectedStateChange, PlannedStep, StepExecutionStrategy

    return PlannedStep(
        plan_step_id=f"plan-{action}",
        source_canonical_step_id="c",
        source_semantic_step_id="s",
        source_dna_step_key=f"hubspot:{action}",
        application="HubSpot",
        action=action,
        description=action,
        resolved_parameters=params or {},
        execution_strategy=StepExecutionStrategy(strategy=ExecutionStrategy.API, reason="test", target_technology="HubSpot"),
        risk=StepRisk(step_id="c", application="HubSpot", action=action, risk_level=RiskLevel.LOW,
                      risk_category=RiskCategory.READ_ONLY, reason="test"),
        expected_result="",
        evidence_reference="",
        state_change=ExpectedStateChange(target_system="HubSpot", entity_or_property="contact", before_state="", expected_after_state=""),
        catalog_action=f"hubspot.{action}",
    )


def _ctx(tmp_path, dry_run=False, **params):
    return ExecutionContext(
        execution_id="exec-hs", workflow_id="wf", execution_plan_id="plan", sandbox_root=str(tmp_path),
        execution_mode=ExecutionMode.DRY_RUN if dry_run else ExecutionMode.LIVE, dry_run=dry_run, resolved_parameters=params,
    )


# -------------------------------------------------------------------- client


def test_client_search_update_and_notes(client, fake):
    assert [c.contact_id for c in client.find_contacts("RAHUL.sharma@example.com")] == ["90001"]  # exact email
    assert {c.contact_id for c in client.find_contacts("Priya")} == {"90002", "90003"}  # text search
    assert client.update_contact("90001", {"replacement_status": "processed"}).properties["replacement_status"] == "processed"
    note = client.create_note("90001", "Invoice received")
    assert fake.notes[note["id"]] == {"body": "Invoice received", "contact": "90001"}
    props = client.list_contact_properties()
    assert [p["name"] for p in props] == ["jobtitle", "replacement_status"]  # read-only properties are left out
    assert props[1]["options"] == ["open", "processed"]


def test_client_errors_are_typed(fake):
    assert HubSpotClient(access_token="wrong-token-xxxxxxxxxxxx", http_client=fake.http()).check_access()[0] is False
    fake.status_override = 429
    with pytest.raises(HubSpotRateLimited) as e:
        HubSpotClient(access_token=TOKEN, http_client=fake.http()).find_contacts("x")
    assert e.value.status_code == 429
    fake.status_override = 403
    assert "crm.objects.contacts.read" in HubSpotClient(access_token=TOKEN, http_client=fake.http()).check_access()[1]


# ------------------------------------------------------------------ executor


def test_find_contact_resolves_one_match_and_pauses_otherwise(client, tmp_path):
    ex = HubSpotApiExecutor(client=client)
    found = ex.execute(_step("find_contact", {"contact_query": "{customer_email}"}), _ctx(tmp_path, customer_email="rahul.sharma@example.com"))
    assert found.status == ExecutionStepStatus.SUCCESS
    assert found.output["contact"]["contact_id"] == "90001" and found.output["contact"]["name"] == "Rahul Sharma"

    several = ex.execute(_step("find_contact", {"contact_query": "Priya"}), _ctx(tmp_path))
    assert several.status == ExecutionStepStatus.NEEDS_INPUT
    assert {c["customer_id"] for c in several.intervention["candidates"]} == {"90002", "90003"}
    assert several.intervention["accepted_inputs"] == ["selected_customer_id", "customer_query"]

    none = ex.execute(_step("find_contact", {"contact_query": "nobody@example.com"}), _ctx(tmp_path))
    assert none.status == ExecutionStepStatus.NEEDS_INPUT and none.intervention["code"] == "NO_MATCH"

    picked = ex.execute(_step("find_contact", {"contact_query": "Priya"}), _ctx(tmp_path, selected_customer_id="90003"))
    assert picked.output["contact"]["contact_id"] == "90003"
    by_id = ex.execute(_step("find_contact", {"contact_query": "90002"}), _ctx(tmp_path))
    assert by_id.output["contact"]["contact_id"] == "90002"


def test_update_contact_needs_a_property_from_settings(client, store, tmp_path):
    ex = HubSpotApiExecutor(client=client)
    blocked = ex.execute(_step("update_contact"), _ctx(tmp_path, contact_id="90001", property_value="processed"))
    assert blocked.status == ExecutionStepStatus.BLOCKED and blocked.blocked_reason == "NOT_CONFIGURED"

    store.put(HUBSPOT, {"access_token": TOKEN}, {"status_property": "replacement_status", "status_value": "processed"})
    done = ex.execute(_step("update_contact"), _ctx(tmp_path, contact_id="90001"))  # value comes from Settings
    assert done.status == ExecutionStepStatus.SUCCESS and done.output["value"] == "processed"

    checker = HubSpotVerificationStrategy(client=client)
    [check] = checker.build_checks("exec-hs", _step("update_contact"), done, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.VERIFIED


def test_add_note_and_missing_scope(client, fake, tmp_path):
    ex = HubSpotApiExecutor(client=client)
    added = ex.execute(_step("add_note"), _ctx(tmp_path, contact_id="90001", email_subject="Replacement request"))
    assert added.status == ExecutionStepStatus.SUCCESS
    assert fake.notes[added.output["note_id"]]["body"] == "WorkFlowOS processed the email 'Replacement request'."
    checker = HubSpotVerificationStrategy(client=client)
    [check] = checker.build_checks("exec-hs", _step("add_note"), added, str(tmp_path))
    assert checker.verify(check, str(tmp_path)).status == VerificationStatus.VERIFIED

    fake.scopes_missing_for_notes = True
    refused = ex.execute(_step("add_note"), _ctx(tmp_path, contact_id="90001"))
    assert refused.status == ExecutionStepStatus.BLOCKED and refused.blocked_reason == "MISSING_SCOPE"


def test_dry_run_and_unconfigured(fake, tmp_path, store):
    ex = HubSpotApiExecutor(client=HubSpotClient(access_token=TOKEN, http_client=fake.http()))
    for action in ("find_contact", "update_contact", "add_note"):
        assert ex.execute(_step(action), _ctx(tmp_path, dry_run=True)).status == ExecutionStepStatus.SUCCESS
    assert fake.calls == []  # dry runs never call HubSpot

    unconfigured = HubSpotApiExecutor(client=HubSpotClient(http_client=fake.http()))
    res = unconfigured.execute(_step("find_contact", {"contact_query": "a@b.com"}), _ctx(tmp_path))
    assert res.status == ExecutionStepStatus.BLOCKED and res.blocked_reason == "INTEGRATION_UNAVAILABLE"


# ------------------------------------------------------------- observation


def _nav(url):
    return ActivityEvent(event_type=ActivityEventType.BROWSER_NAVIGATION, application="Web Browser", metadata={"url": url})


def test_observation_rules():
    rec = classify_lookup(_nav("https://app.hubspot.com/contacts/4812345/record/0-1/90001"))
    assert rec.action == FIND_CONTACT and rec.parameters == {"contact_query": "90001"}
    assert classify_lookup(_nav("https://app-eu1.hubspot.com/contacts/1/contact/7")).parameters == {"contact_query": "7"}
    listed = classify_lookup(_nav("https://app.hubspot.com/contacts/1/objects/0-1/views/all/list?query=a%40b.com"))
    assert listed.parameters == {"contact_query": "a@b.com"}
    assert classify_lookup(_nav("https://app.hubspot.com.evil.example/contacts/1/record/0-1/2")) is None
    assert classify_lookup(_nav("https://www.hubspot.com/contacts/1/record/0-1/2")) is None  # marketing site, not the app

    url = "https://app.hubspot.com/contacts/1/record/0-1/2"
    note = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED, metadata={"url": url, "form_fields": {"kind": "note"}})
    edit = ActivityEvent(event_type=ActivityEventType.FORM_SUBMITTED,
                         metadata={"url": url, "form_fields": {"kind": "property", "property": "jobtitle", "value": "CTO"}})
    assert classify_change(note).action == ADD_NOTE
    assert classify_change(edit).action == UPDATE_CONTACT
    assert classify_change(edit).parameters == {"contact_property": "jobtitle", "property_value": "CTO"}


# ------------------------------------------------------------------ settings


@pytest.fixture
def settings_api(store, fake, monkeypatch):
    svc = integrations_module.IntegrationService(store=store, http_factory=fake.http)
    monkeypatch.setattr(integrations_module, "_service", svc)
    from app.main import create_app

    return TestClient(create_app())


def test_settings_connect_choose_property_and_disconnect(settings_api, store):
    assert settings_api.put("/api/integrations/hubspot", json={"access_token": "wrong-token-xxxxxxxxxxxxxxxx"}).status_code == 400
    ok = settings_api.put("/api/integrations/hubspot", json={"access_token": TOKEN})
    assert ok.status_code == 200 and TOKEN not in ok.text
    assert ok.json()["hubspot"]["portal_id"] == 4812345

    props = settings_api.get("/api/integrations/hubspot/properties").json()
    assert [p["name"] for p in props] == ["jobtitle", "replacement_status"]
    bad = settings_api.put("/api/integrations/hubspot/settings", json={"status_property": "replacement_status", "status_value": "maybe"})
    assert bad.status_code == 400 and "not one of the options" in bad.json()["detail"]
    saved = settings_api.put("/api/integrations/hubspot/settings", json={"status_property": "replacement_status", "status_value": "processed"})
    assert saved.json()["hubspot"]["status_property_label"] == "Replacement status"

    # Reconnecting keeps the chosen property
    settings_api.put("/api/integrations/hubspot", json={"access_token": TOKEN})
    assert store.info(HUBSPOT).metadata["status_property"] == "replacement_status"
    assert settings_api.delete("/api/integrations/hubspot").json()["hubspot"]["configured"] is False


# ------------------------------------------- discovered workflow, end to end


def test_discovered_gmail_hubspot_slack_workflow_runs(tmp_path, fake, store):
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
    from app.services.observed_sessions import GMAIL_SEARCH, SLACK_CHANNEL, build_observed_hubspot_events
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

    # 1. Discover the routine from recorded sessions
    sessions = WorkflowSegmenter().segment(build_observed_hubspot_events())
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    assert [s.catalog_action for s in dna.invariant_steps if s.catalog_action] == [
        "gmail.search_email", "gmail.download_attachment", "hubspot.find_contact",
        "hubspot.update_contact", "hubspot.add_note", "slack.send_notification",
    ]
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    assert semantic.status == "success", semantic.validation_errors
    spec = CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)

    # 2. Approve and plan: the contact comes from the new email's sender, never from a past session
    db = str(tmp_path / "hs.db")
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
    hubspot_steps = {s.action: s.resolved_parameters for s in plan.planned_steps if s.application == "HubSpot"}
    assert hubspot_steps["find_contact"]["contact_query"] == "{customer_email}"
    assert hubspot_steps["update_contact"]["property_value"] == "processed"  # constant across sessions

    # 3. Execute live against fakes
    store.put(HUBSPOT, {"access_token": TOKEN}, {"status_property": "replacement_status"})
    gmail = MagicMock(spec=GmailApiClient)
    gmail.is_configured.return_value = gmail.is_authenticated.return_value = True
    gmail.search_messages.return_value = GmailSearchResult(
        query=GMAIL_SEARCH, total_found=1,
        messages=[GmailMessageSummary(
            message_id="msg-hs-1", thread_id="t", subject="Replacement request", sender="Priya <priya.patel@example.com>",
            has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="a1", filename="invoice.pdf", size_bytes=10)],
        )],
    )
    gmail.download_attachment.return_value = (b"%PDF-1.4 x", {"filename": "invoice.pdf", "mime_type": "application/pdf"})
    slack = MagicMock(spec=SlackApiClient)
    slack.default_channel_id = SLACK_CHANNEL
    slack.send_notification.return_value = SlackNotificationResult(success=True, channel=SLACK_CHANNEL, ts="1.2")
    slack.verify_message.return_value = (True, {"ts": "1.2"}, "found")
    hubspot = HubSpotClient(access_token=TOKEN, http_client=fake.http())

    for ex in (GmailApiExecutor(client=gmail), HubSpotApiExecutor(client=hubspot), SlackApiExecutor(client=slack)):
        orch.engine.registry.register(ex)
    for v in (GmailVerificationStrategy(), HubSpotVerificationStrategy(client=hubspot), SlackVerificationStrategy(client=slack)):
        orch.verification_engine.strategy_registry.register(v)

    record = orch.execute_live(plan.execution_plan_id)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    assert fake.contacts["90002"]["replacement_status"] == "processed"  # Priya, the NEW email's sender
    assert [n["contact"] for n in fake.notes.values()] == ["90002"]
    assert all(c["replacement_status"] == "open" for cid, c in fake.contacts.items() if cid != "90002")

    verification = orch.verify_execution(record.execution_id)
    hubspot_checks = [c for c in verification.checks if c.check_type.startswith("hubspot_")]
    assert [c.status for c in hubspot_checks] == [VerificationStatus.VERIFIED] * 3
