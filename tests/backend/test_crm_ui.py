"""Demo CRM browser UI: the pages a person uses while the agent observes."""

from fastapi.testclient import TestClient
import pytest

from app.crm_server import crm_app
from app.models.crm import CrmCustomer
from app.repositories.crm_repository import CrmRepository


@pytest.fixture
def client():
    repo = CrmRepository()
    repo.clear()
    repo.save(CrmCustomer(customer_id="cust-ui-1", name="Asha <b>Rao</b>", email="asha@example.com", company="Initech", status="pending_replacement"))
    with TestClient(crm_app) as c:
        yield c
    repo.clear()


def test_list_search_and_detail_pages(client):
    page = client.get("/ui/customers")
    assert page.status_code == 200
    assert "WorkFlowOS CRM</title>" in page.text
    assert "/ui/customers/cust-ui-1" in page.text
    # Customer data is HTML-escaped
    assert "<b>Rao</b>" not in page.text and "&lt;b&gt;Rao&lt;/b&gt;" in page.text

    assert "cust-ui-1" in client.get("/ui/customers", params={"q": "asha@"}).text
    assert "No customers found" in client.get("/ui/customers", params={"q": "nobody"}).text

    detail = client.get("/ui/customers/cust-ui-1")
    assert detail.status_code == 200
    assert "<option value='pending_replacement' selected>" in detail.text
    assert client.get("/ui/customers/missing").status_code == 404


def test_form_submission_updates_status(client):
    res = client.post(
        "/ui/customers/cust-ui-1",
        content="status=replacement_processed&notes=Invoice+received",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/ui/customers/cust-ui-1"
    updated = CrmRepository().get_by_id("cust-ui-1")
    assert updated.status == "replacement_processed"
    assert updated.notes == "Invoice received"

    missing_status = client.post(
        "/ui/customers/cust-ui-1", content="notes=x", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert missing_status.status_code == 422
