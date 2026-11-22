"""Rules every integration in app/integrations/ must follow (they apply to new ones automatically)."""

from fastapi.testclient import TestClient

from app.integrations import INTEGRATIONS, all_actions, get_integration
from app.main import create_app
from app.models.event import ActivityEvent, ActivityEventType
from app.services import action_catalog
from app.services.executors.registry import ExecutorRegistry
from app.services.observed_sessions import build_observed_events
from app.services.verifiers.registry import VerificationStrategyRegistry


def _sample_events():
    events = list(build_observed_events())
    for url in (
        "https://mail.google.com/mail/u/0/#search/invoice",
        "http://127.0.0.1:8001/ui/customers/cust-1",
        "https://app.slack.com/client/T1/C0ABCDEF12",
        "https://example.com/page",
    ):
        for event_type in (ActivityEventType.BROWSER_NAVIGATION, ActivityEventType.FORM_SUBMITTED, ActivityEventType.FILE_DOWNLOADED):
            events.append(ActivityEvent(event_type=event_type, application="Web Browser", metadata={"url": url, "form_fields": {"status": "x"}}))
    return events


def test_keys_are_unique_and_action_ids_are_namespaced():
    keys = [i.key for i in INTEGRATIONS]
    assert len(keys) == len(set(keys))
    for integration in INTEGRATIONS:
        assert integration.actions, f"{integration.key} declares no actions"
        for action in integration.actions:
            assert action.action_id == f"{integration.key}.{action.action}", action.action_id
    assert set(action_catalog.ACTION_CATALOG) == set(all_actions())


def test_every_action_routes_to_an_executor_its_integration_provides():
    for integration in INTEGRATIONS:
        executors = {e.name: e for e in (make() for make in integration.executors)}
        for action in integration.actions:
            executor = executors.get(action.executor_name)
            assert executor is not None, f"{action.action_id} -> {action.executor_name} is not provided by {integration.key}"
            cap = executor.capability
            assert cap.implemented
            assert action.action in cap.supported_actions, f"{executor.name} does not declare {action.action}"
            assert any(t.lower() == action.application.lower() for t in cap.supported_targets)


def test_registries_contain_every_integration_executor_and_verifier():
    executors = set(ExecutorRegistry().list_executors())
    verifiers = set(VerificationStrategyRegistry().list_strategies())
    for integration in INTEGRATIONS:
        assert {make().name for make in integration.executors} <= executors
        assert {make().name for make in integration.verifiers} <= verifiers


def test_classifiers_only_return_their_own_actions_and_never_overlap():
    for event in _sample_events():
        claims = []
        for integration in INTEGRATIONS:
            for classifier in integration.classifiers:
                found = classifier(event)
                if found is not None:
                    assert found.action in integration.actions, f"{integration.key} classified into {found.action.action_id}"
                    claims.append(integration.key)
        assert len(claims) <= 1, f"{event.metadata.get('url')} {event.event_type}: claimed by {claims}"


def test_status_reports_every_integration(monkeypatch):
    from app.services.crm_client import CrmApiClient

    monkeypatch.setattr(CrmApiClient, "is_healthy", lambda self: False)  # no network in tests
    body = TestClient(create_app()).get("/api/status").json()
    listed = [i["key"] for i in body["integrations"]]
    assert listed == [i.key for i in INTEGRATIONS]
    for integration in INTEGRATIONS:
        assert set(body[integration.key]) == {"connected", "detail"}
    assert get_integration("gmail").name == "Gmail" and get_integration("nope") is None


def test_a_broken_status_check_does_not_hide_the_others(monkeypatch):
    import dataclasses

    import app.integrations as registry

    broken = dataclasses.replace(registry.INTEGRATIONS[0], status=lambda: 1 / 0)
    from app.services.crm_client import CrmApiClient

    monkeypatch.setattr(CrmApiClient, "is_healthy", lambda self: False)
    monkeypatch.setattr(registry, "INTEGRATIONS", [broken, *registry.INTEGRATIONS[1:]])
    body = TestClient(create_app()).get("/api/status").json()
    assert body[broken.key] == {"connected": False, "detail": "Status check failed: ZeroDivisionError."}
    assert all(k in body for k in ("crm", "slack", "ai"))
