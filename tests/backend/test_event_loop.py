"""The API never blocks its event loop.

An `async def` endpoint runs on the event loop itself, so any blocking call inside it (database,
Gmail, CRM, Slack) stalls every other request until it returns. WorkFlowOS endpoints are plain
`def` (FastAPI runs them in a thread pool); slow external work goes to the worker.
"""

import asyncio
import inspect
import time

import httpx

from app.api import execution
from app.crm_server import crm_app
from app.main import create_app

# async endpoints that are known not to block (they hand blocking work to a thread themselves)
ALLOWED_ASYNC = {("crm", "customer_update")}


def _async_endpoints(app, name):
    return {
        (name, route.endpoint.__name__)
        for route in app.routes
        if getattr(route, "endpoint", None)
        and inspect.iscoroutinefunction(route.endpoint)
        # FastAPI's own /docs, /redoc and /openapi.json handlers don't block
        and route.endpoint.__module__.startswith("app.")
    }


def test_no_async_endpoints_that_could_block():
    found = _async_endpoints(create_app(), "api") | _async_endpoints(crm_app, "crm")
    assert found - ALLOWED_ASYNC == set(), (
        f"Make these plain `def` (or move blocking work off the event loop): {sorted(found - ALLOWED_ASYNC)}"
    )


def test_slow_requests_are_served_concurrently(monkeypatch):
    """Three requests that each wait 1s on the database finish together, not one after another."""

    def slow_lookup(execution_id):
        time.sleep(1.0)
        return None

    monkeypatch.setattr(execution.exec_repo, "get_by_id", slow_lookup)
    app = create_app()

    async def three_at_once():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = time.perf_counter()
            responses = await asyncio.gather(
                *(client.get(f"/api/workflows/executions/missing-{i}") for i in range(3))
            )
            return time.perf_counter() - started, responses

    elapsed, responses = asyncio.run(three_at_once())
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert elapsed < 2.5, f"requests were serialised ({elapsed:.1f}s for 3 x 1s)"
