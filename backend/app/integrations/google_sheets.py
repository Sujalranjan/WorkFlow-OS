"""Google Sheets: add a row about each run to the team's log sheet (opt-in; see services/google_sheets.py).

Observation is coarse on purpose: Sheets does not expose what was typed, so opening the same
spreadsheet in every recorded run of a routine is learned as "add a row to that log sheet". The
row's contents come from the columns chosen in Settings, never from what was typed while recording.
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration, host
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

_SHEET_PATH_RE = re.compile(r"^/spreadsheets/d/([A-Za-z0-9_-]{20,100})(?:/|$)")

APPEND_ROW = CatalogAction(
    action_id="sheets.append_row",
    application="Google Sheets",
    action="append_row",
    description="Add a row about this run to the Google Sheet chosen in Settings",
    executor_name="GoogleSheetsExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.EXTERNAL_CHANGE,
    risk_reason="Adds a row to a Google Sheet (existing cells are never changed).",
    parameters=(
        CatalogParameter("spreadsheet_id", "The spreadsheet seen while recording (must match Settings)", required=False),
    ),
    produces=("sheet_row_range",),
)


def classify_open_sheet(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    if evt.event_type != ActivityEventType.BROWSER_NAVIGATION:
        return None
    url = evt.metadata.get("url") or evt.metadata.get("tab_url")
    if not isinstance(url, str) or host(url) != "docs.google.com":
        return None
    m = _SHEET_PATH_RE.match(urlparse(url).path)
    return ClassifiedAction(APPEND_ROW, {"spreadsheet_id": m.group(1)}) if m else None


def _executor():
    from app.services.executors.sheets_executor import GoogleSheetsExecutor

    return GoogleSheetsExecutor()


def _verifier():
    from app.services.verifiers.sheets_verifier import GoogleSheetsVerificationStrategy

    return GoogleSheetsVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.google_sheets import configured_sheet, sheets_status

    problem = sheets_status()
    if problem:
        return False, problem
    sheet = configured_sheet()
    if not sheet:
        return False, "No spreadsheet chosen in Settings."
    return True, f"Adding rows to '{sheet.get('title')}' ({sheet.get('sheet')})."


SHEETS = Integration(
    key="sheets",
    name="Google Sheets",
    role="Logs each run as a row in the team's sheet",
    actions=(APPEND_ROW,),
    classifiers=(classify_open_sheet,),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)
