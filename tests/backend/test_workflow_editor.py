"""Workflow editor: validation against the catalog, versions, re-approval, the API, and that an
edited workflow plans and runs exactly as edited (and an old plan cannot run after an edit)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from app.models.canonical import ApprovalState, StepParameter, StepParameterMode
from app.models.execution_plan import ParameterResolutionStatus
from app.repositories.canonical_repository import CanonicalWorkflowRepository, WorkflowConflict
from app.services import workflow_editor as we
from app.services.execution_planner import ExecutionPlanner
from app.services.observed_sessions import build_observed_events, build_observed_folder_events


def _discover(events):
    from app.services.canonical_factory import CanonicalWorkflowFactory
    from app.services.semantic_engine import SemanticUnderstandingEngine
    from app.services.semantic_provider import MockSemanticProvider
    from app.services.workflow_discovery import WorkflowDiscoveryEngine
    from app.services.workflow_dna_extractor import WorkflowDNAExtractor
    from app.services.workflow_segmenter import WorkflowSegmenter

    sessions = WorkflowSegmenter().segment(events)
    [candidate] = WorkflowDiscoveryEngine().discover_candidates(sessions)
    dna = WorkflowDNAExtractor().extract_dna(candidate, [s for s in sessions if s.session_id in candidate.supporting_session_ids])
    semantic = SemanticUnderstandingEngine(provider=MockSemanticProvider()).interpret_dna(dna)
    return CanonicalWorkflowFactory().create_specification(dna, semantic.semantic_workflow)


@pytest.fixture
def crm_spec():
    """Gmail -> attachment -> CRM find (customer differs per run) -> CRM update -> Slack."""
    return _discover(build_observed_events())


def _definition(spec, **changes):
    d = we.current_definition(spec)
    body = {
        "base_version": d["version"],
        "title": d["title"],
        "description": d["description"],
        "steps": [{"step_id": s["step_id"], "catalog_action": s["catalog_action"], "parameters": s["parameters"]} for s in d["steps"]],
    }
    body.update(changes)
    return we.WorkflowDefinition(**body)


def _errors(spec, definition):
    return [i.message for i in we.validate(spec, definition) if i.level == "error"]


def _step_index(defn, action):
    return next(i for i, s in enumerate(defn.steps) if s.catalog_action == action)


# ------------------------------------------------------------- current state


def test_current_definition_shows_where_each_input_comes_from(crm_spec):
    d = we.current_definition(crm_spec)
    assert [s["catalog_action"] for s in d["steps"]] == [
        "gmail.search_email", "gmail.download_attachment", "crm.find_customer",
        "crm.update_customer_record", "slack.send_notification",
    ]
    find = d["steps"][2]["parameters"]["customer_query"]
    assert find == {"mode": "upstream", "value": "customer_email"}  # varied between runs -> from the new email
    assert d["steps"][0]["parameters"]["search_query"]["mode"] == "fixed"  # the same in every run
    assert d["context_steps"]  # window focus etc. are shown as not runnable
    assert we.validate(crm_spec, _definition(crm_spec)) == []  # the recorded workflow is valid as it is


# ---------------------------------------------------------------- validation


def test_steps_must_come_after_what_they_need(crm_spec):
    defn = _definition(crm_spec)
    find, update = _step_index(defn, "crm.find_customer"), _step_index(defn, "crm.update_customer_record")
    defn.steps[find], defn.steps[update] = defn.steps[update], defn.steps[find]
    errors = _errors(crm_spec, defn)
    assert any("needs 'customer_id'" in e for e in errors)

    reply_first = _definition(crm_spec)
    reply_first.steps.insert(0, we.EditedStep(catalog_action="slack.reply_in_thread",
                                              parameters={"thread_ts": StepParameter(mode="upstream", value="slack_ts")}))
    errors = _errors(crm_spec, reply_first)
    assert any("needs 'slack_ts'" in e for e in errors) and any("'slack_ts' is not produced" in e for e in errors)

    reply_last = _definition(crm_spec)
    reply_last.steps.append(we.EditedStep(catalog_action="slack.reply_in_thread",
                                          parameters={"thread_ts": StepParameter(mode="upstream", value="slack_ts")}))
    assert _errors(crm_spec, reply_last) == []


def test_a_value_that_changed_between_runs_cannot_be_pinned_to_a_recorded_one(crm_spec):
    recorded = next(v for (k, p), vals in we.recorded_values(crm_spec).items() if p == "customer_query" for v in vals)
    defn = _definition(crm_spec)
    defn.steps[_step_index(defn, "crm.find_customer")].parameters["customer_query"] = StepParameter(mode="fixed", value=recorded)
    assert any("from one recorded run" in e for e in _errors(crm_spec, defn))
    # a deliberate different constant (e.g. a shared account) is allowed
    defn.steps[_step_index(defn, "crm.find_customer")].parameters["customer_query"] = StepParameter(mode="fixed", value="cust-999")
    assert _errors(crm_spec, defn) == []


def test_catalog_rules(crm_spec):
    base = _definition(crm_spec)
    cases = [
        (we.EditedStep(catalog_action="shell.run_command"), "not an action WorkFlowOS can run"),
        (we.EditedStep(catalog_action="hubspot.find_contact", parameters={"bogus": StepParameter(mode="fixed", value="x")}),
         "'bogus' is not an input"),
        (we.EditedStep(catalog_action="hubspot.find_contact"), "Choose where 'contact_query' comes from"),
        (we.EditedStep(catalog_action="hubspot.find_contact",
                       parameters={"contact_query": StepParameter(mode="fixed", value="{customer_email}")}), "choose 'From an earlier step'"),
        (we.EditedStep(catalog_action="hubspot.find_contact",
                       parameters={"contact_query": StepParameter(mode="upstream", value="note_id")}), "'note_id' is not produced"),
        (we.EditedStep(step_id="can-step-999", catalog_action="slack.send_notification"), "does not belong to this workflow"),
    ]
    for step, expected in cases:
        defn = base.model_copy(deep=True)
        defn.steps.append(step)
        assert any(expected in e for e in _errors(crm_spec, defn)), expected
    dup = base.model_copy(deep=True)
    dup.steps.append(dup.steps[0].model_copy())
    assert any("appears twice" in e for e in _errors(crm_spec, dup))
    stale = base.model_copy(update={"base_version": "0.9.0"})
    assert any("Reload it" in e for e in _errors(crm_spec, stale))


# ------------------------------------------------------- apply, plan and run


def test_edit_makes_a_new_version_that_needs_approval_and_plans_as_edited(crm_spec, tmp_path):
    repo = CanonicalWorkflowRepository(str(tmp_path / "e.db"))
    crm_spec = crm_spec.model_copy(update={"approval_state": crm_spec.approval_state.model_copy(update={"state": ApprovalState.APPROVED})})
    repo.save(crm_spec)
    old_plan = ExecutionPlanner().create_execution_plan(crm_spec)

    defn = _definition(crm_spec, title="Replacement requests (labelled)", note="label processed mail")
    defn.steps.insert(1, we.EditedStep(catalog_action="gmail.add_label", parameters={
        "message_id": StepParameter(mode="upstream", value="message_id"),
        "label": StepParameter(mode="fixed", value="Processed"),
    }))
    defn.steps[_step_index(defn, "crm.update_customer_record")].parameters["customer_status"] = StepParameter(mode="runtime")
    assert _errors(crm_spec, defn) == []
    edited = we.apply(crm_spec, defn, "editor@example.com")
    changes = we.changes_between(crm_spec, edited)
    saved = repo.save_edit(crm_spec, edited, "editor@example.com", defn.note, changes)

    assert saved.version == "1.1.0" and saved.approval_state.state == ApprovalState.REQUIRES_REVIEW
    texts = [c["text"] for c in changes]
    assert any(t.startswith("Added step 2: Gmail") for t in texts)
    assert any("'customer_status'" in t and "asked at run time" in t for t in texts)
    assert [v["version"] for v in repo.list_versions(crm_spec.workflow_id)] == ["1.1.0", "1.0.0"]
    assert repo.get_version(crm_spec.workflow_id, "1.0.0").title == crm_spec.title

    with pytest.raises(ValueError, match="APPROVED"):  # nothing runs until approved again
        ExecutionPlanner().create_execution_plan(saved)
    with pytest.raises(WorkflowConflict):  # the reviewer must have looked at this version
        repo.update_approval_state(crm_spec.workflow_id, ApprovalState.APPROVED, "boss", expected_version="1.0.0")
    approved = repo.update_approval_state(crm_spec.workflow_id, ApprovalState.APPROVED, "boss", expected_version="1.1.0")

    plan = ExecutionPlanner().create_execution_plan(approved, runtime_inputs={"customer_status": "replaced", "label": "Other"})
    by_action = {s.catalog_action: s.resolved_parameters for s in plan.planned_steps}
    assert by_action["gmail.add_label"] == {"message_id": "{message_id}", "label": "Processed"}  # fixed wins over run input
    assert by_action["crm.update_customer_record"]["customer_status"] == "replaced"  # runtime input fills 'ask at run time'
    assert by_action["crm.find_customer"]["customer_query"] == "{customer_email}"
    assert not plan.excluded_steps  # edited versions hold only runnable steps

    unresolved = ExecutionPlanner().create_execution_plan(approved)
    status = {p.source_parameter: p.resolution_status for p in unresolved.resolved_parameters}
    assert any(k.endswith(".customer_status") and v == ParameterResolutionStatus.UNRESOLVED for k, v in status.items())

    from app.services.execution_policy import ExecutionPolicyEngine

    ok, violations = ExecutionPolicyEngine().validate_plan_execution(approved, old_plan)
    assert not ok and any("made for version 1.0.0" in v for v in violations)  # an old plan cannot run the new version


def test_concurrent_saves_and_decisions_never_overwrite_each_other(crm_spec, tmp_path):
    repo = CanonicalWorkflowRepository(str(tmp_path / "c.db"))
    repo.save(crm_spec)
    first = we.apply(crm_spec, _definition(crm_spec, title="A"), "a")
    second = we.apply(crm_spec, _definition(crm_spec, title="B"), "b")
    repo.save_edit(crm_spec, first, "a", None, [{"kind": "title", "text": "A"}])
    with pytest.raises(WorkflowConflict):
        repo.save_edit(crm_spec, second, "b", None, [{"kind": "title", "text": "B"}])
    assert repo.get_by_id(crm_spec.workflow_id).title == "A"


def test_edited_workflow_runs_the_added_step(tmp_path):
    """A recorded Gmail -> folder -> Slack routine, edited to also reply in the Slack thread, runs live."""
    from cryptography.fernet import Fernet

    from app.models.execution import ExecutionOverallStatus
    from app.models.gmail import GmailAttachmentInfo, GmailMessageSummary, GmailSearchResult
    from app.repositories.execution_plan_repository import ExecutionPlanRepository
    from app.repositories.execution_repository import ExecutionRepository
    from app.services.credential_store import SHARED_FOLDER, CredentialStore, set_credential_store
    from app.services.execution_engine import ExecutionEngine
    from app.services.executors.gmail_executor import GmailApiExecutor
    from app.services.executors.slack_executor import SlackApiExecutor
    from app.services.gmail_client import GmailApiClient
    from app.services.observed_sessions import GMAIL_SEARCH
    from tests.backend.test_slack_thread import FakeSlack

    spec = _discover(build_observed_folder_events())
    db = str(tmp_path / "run.db")
    repo, plans, execs = CanonicalWorkflowRepository(db), ExecutionPlanRepository(db), ExecutionRepository(db)
    repo.save(spec)
    defn = _definition(spec, note="say when done")
    defn.steps.append(we.EditedStep(catalog_action="slack.reply_in_thread",
                                    parameters={"thread_ts": StepParameter(mode="upstream", value="slack_ts")}))
    edited = repo.save_edit(spec, we.apply(spec, defn, "ed"), "ed", defn.note, we.changes_between(spec, we.apply(spec, defn, "ed")))
    approved = repo.update_approval_state(spec.workflow_id, ApprovalState.APPROVED, "boss", expected_version=edited.version)
    plan = plans.save(ExecutionPlanner().create_execution_plan(approved))

    folder = tmp_path / "shared"
    folder.mkdir()
    store = CredentialStore(str(tmp_path / "creds.db"), Fernet.generate_key())
    store.put(SHARED_FOLDER, {}, {"folder": str(folder)})
    set_credential_store(store)
    try:
        gmail = MagicMock(spec=GmailApiClient)
        gmail.is_configured.return_value = gmail.is_authenticated.return_value = True
        gmail.search_messages.return_value = GmailSearchResult(
            query=GMAIL_SEARCH, total_found=1,
            messages=[GmailMessageSummary(message_id="m1", thread_id="t", subject="Replacement request", sender="a@example.com",
                                          has_attachments=True, attachments=[GmailAttachmentInfo(attachment_id="x", filename="inv.pdf", size_bytes=3)])],
        )
        gmail.download_attachment.return_value = (b"pdf", {"filename": "inv.pdf", "mime_type": "application/pdf"})
        fake = FakeSlack()
        engine = ExecutionEngine(canonical_repo=repo, plan_repo=plans, exec_repo=execs, default_sandbox_base=str(tmp_path / "sb"))
        engine.registry.register(GmailApiExecutor(client=gmail))
        engine.registry.register(SlackApiExecutor(client=fake.client()))
        record = engine.execute_plan(plan.execution_plan_id)
    finally:
        set_credential_store(None)
    assert record.status == ExecutionOverallStatus.COMPLETED, record.error_summary
    top, reply = fake.posts
    assert reply["thread_ts"] == fake.messages[0]["ts"]
    assert "Saved to the shared folder as: inv.pdf" in reply["text"]


# ----------------------------------------------------------------------- API


@pytest.fixture
def api(crm_spec, tmp_path):
    from app.api.canonical import get_canonical_repository
    from app.main import create_app

    repo = CanonicalWorkflowRepository(str(tmp_path / "api.db"))
    repo.save(crm_spec)
    app = create_app()
    app.dependency_overrides[get_canonical_repository] = lambda: repo
    return TestClient(app), repo


def test_editor_api(api, crm_spec):
    client, repo = api
    wid = crm_spec.workflow_id
    catalog = client.get("/api/catalog").json()
    reply = next(a for g in catalog for a in g["actions"] if a["action_id"] == "slack.reply_in_thread")
    assert reply["requires"] == ["slack_ts"] and reply["parameters"][0]["default_upstream"] == "slack_ts"

    d = client.get(f"/api/workflows/specifications/{wid}/definition").json()
    body = {"base_version": d["version"], "title": d["title"], "description": d["description"],
            "steps": [{k: s[k] for k in ("step_id", "catalog_action", "parameters")} for s in d["steps"]]}

    assert client.put(f"/api/workflows/specifications/{wid}/definition", json=body).status_code == 400  # nothing changed
    bad = dict(body, steps=body["steps"][::-1])
    check = client.post(f"/api/workflows/specifications/{wid}/definition/validate", json=bad).json()
    assert check["valid"] is False and any(i["level"] == "error" for i in check["issues"])
    refused = client.put(f"/api/workflows/specifications/{wid}/definition", json=bad)
    assert refused.status_code == 422 and refused.json()["detail"]["issues"]

    saved = client.put(f"/api/workflows/specifications/{wid}/definition", json=dict(body, title="Edited", note="rename"))
    assert saved.status_code == 200 and saved.json()["version"] == "1.1.0"
    assert saved.json()["approval_state"]["state"] == "requires_review"
    assert client.put(f"/api/workflows/specifications/{wid}/definition", json=dict(body, title="Again")).status_code == 409  # stale base

    versions = client.get(f"/api/workflows/specifications/{wid}/versions").json()
    assert versions["current_version"] == "1.1.0"
    assert [v["version"] for v in versions["versions"]] == ["1.1.0", "1.0.0"]
    assert versions["versions"][0]["created_by"] == "test-admin@example.com" and versions["versions"][0]["note"] == "rename"
    assert client.get(f"/api/workflows/specifications/{wid}/versions/1.0.0").json()["title"] == crm_spec.title

    stale = client.post(f"/api/workflows/specifications/{wid}/approve", json={"version": "1.0.0"})
    assert stale.status_code == 409
    ok = client.post(f"/api/workflows/specifications/{wid}/approve", json={"version": "1.1.0"})
    assert ok.status_code == 200 and ok.json()["approval_state"]["state"] == "approved"


def test_editing_routes_need_an_approver():
    from app.security import ROUTE_POLICY, Role

    for method, path in [
        ("PUT", "/api/workflows/specifications/{workflow_id}/definition"),
        ("POST", "/api/workflows/specifications/{workflow_id}/definition/validate"),
    ]:
        assert ROUTE_POLICY[(method, path)] == Role.APPROVER
    assert ROUTE_POLICY[("GET", "/api/workflows/specifications/{workflow_id}/versions")] == Role.VIEWER
