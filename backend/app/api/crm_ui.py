"""Browser UI for the WorkFlowOS Demo CRM.

A deliberately small server-rendered UI so a person can do the CRM part of a routine by
hand in the browser. The URLs are the contract the ActionCatalog classifier observes:

    GET  /ui/customers?q=<query>     -> crm.find_customer   (customer_query=<query>)
    GET  /ui/customers/<id>          -> crm.find_customer   (customer_query=<id>)
    POST /ui/customers/<id>  status  -> crm.update_customer_record (customer_status=<status>)

Every page title contains "WorkFlowOS CRM" so the window collector can name the app.
"""

from html import escape
from typing import Optional
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.crm_repository import CrmRepository

router = APIRouter(prefix="/ui", tags=["Demo CRM UI"], include_in_schema=False)

STATUS_OPTIONS = ("ACTIVE", "pending_replacement", "replacement_processed", "INVOICE_PROCESSED", "closed")

_STYLE = """
:root { color-scheme: light dark; --fg:#1d2733; --muted:#5b6775; --bg:#f6f7f9; --card:#fff; --line:#dde2e8; --accent:#2f6fde; }
@media (prefers-color-scheme: dark) { :root { --fg:#e6e9ee; --muted:#9aa5b1; --bg:#14181d; --card:#1c2128; --line:#2c333c; --accent:#6d9ef0; } }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 system-ui, sans-serif; color:var(--fg); background:var(--bg); }
header { padding:14px 24px; border-bottom:1px solid var(--line); background:var(--card); }
header a { color:var(--fg); text-decoration:none; font-weight:600; }
main { max-width:880px; margin:24px auto; padding:0 16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:20px; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:500; font-size:13px; }
a { color:var(--accent); }
form.search { display:flex; gap:8px; margin-bottom:16px; }
input, select, textarea, button { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); }
input[type=search] { flex:1; }
button { background:var(--accent); color:#fff; border-color:var(--accent); cursor:pointer; }
dl { display:grid; grid-template-columns:140px 1fr; gap:6px 12px; margin:0 0 20px; }
dt { color:var(--muted); }
label { display:block; margin:12px 0 4px; color:var(--muted); font-size:13px; }
textarea { width:100%; min-height:70px; }
.empty { color:var(--muted); }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} - WorkFlowOS CRM</title><style>{_STYLE}</style></head>"
        f"<body><header><a href='/ui/customers'>WorkFlowOS CRM</a></header><main>{body}</main></body></html>"
    )


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def ui_root() -> RedirectResponse:
    return RedirectResponse("/ui/customers", status_code=status.HTTP_302_FOUND)


@router.get("/customers", response_class=HTMLResponse)
def customer_list(q: Optional[str] = None) -> HTMLResponse:
    repo = CrmRepository()
    query = (q or "").strip()
    customers = repo.find(query=query, limit=50) if query else repo.list_all(limit=50)

    rows = "".join(
        f"<tr><td><a href='/ui/customers/{quote(c.customer_id)}'>{escape(c.customer_id)}</a></td>"
        f"<td>{escape(c.name)}</td><td>{escape(c.email)}</td><td>{escape(c.company)}</td><td>{escape(c.status)}</td></tr>"
        for c in customers
    )
    table = (
        f"<table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Company</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if customers
        else "<p class='empty'>No customers found.</p>"
    )
    body = (
        "<div class='card'>"
        "<form class='search' method='get' action='/ui/customers'>"
        f"<input type='search' name='q' placeholder='Search by id, name, email or company' value='{escape(query)}'>"
        "<button type='submit'>Search</button></form>"
        f"{table}</div>"
    )
    return _page(f"Customers{': ' + query if query else ''}", body)


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_detail(customer_id: str) -> HTMLResponse:
    customer = CrmRepository().get_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{customer_id}' not found.")

    options = list(STATUS_OPTIONS)
    if customer.status not in options:
        options.insert(0, customer.status)
    select = "".join(
        f"<option value='{escape(o)}'{' selected' if o == customer.status else ''}>{escape(o)}</option>" for o in options
    )
    body = (
        "<div class='card'>"
        f"<h2 style='margin-top:0'>{escape(customer.name)}</h2>"
        "<dl>"
        f"<dt>Customer ID</dt><dd>{escape(customer.customer_id)}</dd>"
        f"<dt>Email</dt><dd>{escape(customer.email)}</dd>"
        f"<dt>Company</dt><dd>{escape(customer.company)}</dd>"
        f"<dt>Status</dt><dd>{escape(customer.status)}</dd>"
        f"<dt>Updated</dt><dd>{escape(customer.updated_at)}</dd>"
        "</dl>"
        f"<form method='post' action='/ui/customers/{quote(customer.customer_id)}'>"
        f"<label for='status'>Status</label><select id='status' name='status'>{select}</select>"
        f"<label for='notes'>Notes</label><textarea id='notes' name='notes'>{escape(customer.notes or '')}</textarea>"
        "<p><button type='submit'>Save</button></p></form></div>"
    )
    return _page(f"Customer {customer.customer_id}", body)


@router.post("/customers/{customer_id}")
async def customer_update(customer_id: str, request: Request) -> RedirectResponse:
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    updates = {k: form[k][0] for k in ("status", "notes") if k in form}
    if not updates.get("status"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="'status' is required.")
    if not CrmRepository().update(customer_id, updates):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{customer_id}' not found.")
    return RedirectResponse(f"/ui/customers/{quote(customer_id)}", status_code=status.HTTP_303_SEE_OTHER)
