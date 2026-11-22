"""Google Sheets for sheets.append_row: add one row describing a run to the sheet chosen in Settings.

- Opt-in: an admin turns on "Allow Google Sheets" (Settings > Gmail), and the next Connect Gmail
  asks Google for the spreadsheets permission. Without both, steps are BLOCKED with what to do.
- Only the spreadsheet and tab chosen in Settings are ever written, and only by appending a row
  (values.append with INSERT_ROWS): existing cells are never changed or cleared.
- Values are written RAW: text such as "=IMPORTXML(...)" from an email subject stays text and is
  never evaluated as a formula.
- The columns are chosen in Settings from a fixed list of run facts (COLUMNS); nothing else from a
  run, and never an email's body, is written.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from app import config

COLUMNS: Dict[str, str] = {
    "date": "When the run did this step (UTC)",
    "email_subject": "Subject of the email the run processed",
    "customer_email": "Sender of that email (or the CRM contact's email)",
    "customer_name": "Customer or contact name found in the CRM",
    "filename": "Attachment name",
    "saved_file_name": "Name of the copy in the shared folder",
    "customer_status": "CRM status after the run",
    "execution_id": "WorkFlowOS run id",
    "workflow_id": "WorkFlowOS workflow id",
}
DEFAULT_COLUMNS = ("date", "email_subject", "customer_email", "filename")

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
_URL_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,100})")
_MAX_CELL = 5000


class SheetsError(Exception):
    code = "FAILED"


class SheetsNotAllowed(SheetsError):
    code = "MISSING_SCOPE"


class SheetNotConfigured(SheetsError):
    code = "NOT_CONFIGURED"


def parse_spreadsheet_id(value: str) -> Optional[str]:
    """A spreadsheet id from its link (docs.google.com/spreadsheets/d/<id>/edit...) or the id itself."""
    text = (value or "").strip()
    m = _URL_RE.search(text)
    if m:
        return m.group(1)
    return text if _ID_RE.match(text) else None


def sheets_status() -> Optional[str]:
    """None when Google Sheets may be used; otherwise what an admin has to do first."""
    from app.services.credential_store import GMAIL_OPTIONS, GMAIL_TOKEN, get_credential_store

    store = get_credential_store()
    options = store.info(GMAIL_OPTIONS)
    if not (options and options.metadata.get("allow_sheets")):
        return "Google Sheets is off. Turn on \"Allow Google Sheets\" in Settings > Integrations > Gmail, then reconnect Gmail."
    token = store.info(GMAIL_TOKEN)
    if not token:
        return "Google is not connected. Connect Gmail in Settings."
    if config.SHEETS_SCOPE not in (token.metadata.get("scopes") or []):
        return "Google has not granted Sheets access yet. Click Reconnect Gmail in Settings and allow it."
    return None


def configured_sheet() -> Optional[Dict[str, Any]]:
    from app.services.credential_store import SHEETS, get_credential_store

    info = get_credential_store().info(SHEETS)
    return dict(info.metadata) if info and info.metadata.get("spreadsheet_id") else None


def a1_tab(sheet: str) -> str:
    """A tab name quoted for A1 notation ('It''s' for It's)."""
    return "'" + sheet.replace("'", "''") + "'"


def build_row(columns: List[str], params: Dict[str, Any], now: Optional[datetime] = None) -> List[str]:
    """The row for one run: one cell per chosen column, from the run's own results."""
    row = []
    for col in columns:
        if col == "date":
            value = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            raw = params.get(col)
            value = "" if raw is None or (isinstance(raw, str) and raw.startswith("{") and raw.endswith("}")) else str(raw)
        row.append(value[:_MAX_CELL])
    return row


def _http_error(e: Exception) -> SheetsError:
    status = getattr(getattr(e, "resp", None), "status", None)
    if status in (401, 403):
        err = SheetsNotAllowed("Google refused access to this spreadsheet (share it with the connected account, or reconnect Gmail).")
        return err
    if status == 404:
        return SheetNotConfigured("Google cannot find that spreadsheet.")
    return SheetsError(f"Google Sheets error: {type(e).__name__}")


class GoogleSheetsClient:
    """Reads spreadsheet metadata, appends rows, reads back a range. `service` lets tests inject a fake."""

    SCOPES = [*config.GMAIL_SCOPES, config.SHEETS_SCOPE]

    def __init__(self, service: Optional[Any] = None, check_permission: bool = True) -> None:
        self._service = service
        self._check_permission = check_permission

    def _sheets(self) -> Any:
        if self._check_permission:
            problem = sheets_status()
            if problem:
                raise SheetsNotAllowed(problem)
        if self._service is not None:
            return self._service
        from googleapiclient.discovery import build

        from app.services.gmail_client import GmailApiClient

        creds = GmailApiClient(scopes=self.SCOPES).google_credentials()
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def spreadsheet(self, spreadsheet_id: str) -> Dict[str, Any]:
        try:
            res = (
                self._sheets()
                .spreadsheets()
                .get(spreadsheetId=spreadsheet_id, fields="properties.title,sheets.properties.title")
                .execute()
            )
        except SheetsError:
            raise
        except Exception as e:
            raise _http_error(e)
        tabs = [s["properties"]["title"] for s in res.get("sheets") or [] if s.get("properties", {}).get("title")]
        if not tabs:
            raise SheetNotConfigured("That spreadsheet has no tabs.")
        return {"title": (res.get("properties") or {}).get("title") or spreadsheet_id, "sheets": tabs}

    def append_row(self, spreadsheet_id: str, sheet: str, row: List[str]) -> str:
        """Append one row after the last row of the tab; returns the range it landed in (e.g. 'Log'!A7:D7)."""
        try:
            res = (
                self._sheets()
                .spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=f"{a1_tab(sheet)}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute()
            )
        except SheetsError:
            raise
        except Exception as e:
            raise _http_error(e)
        updated = (res.get("updates") or {}).get("updatedRange")
        if not updated:
            raise SheetsError("Google did not report where the row was added.")
        return updated

    def read_range(self, spreadsheet_id: str, a1_range: str) -> List[List[str]]:
        try:
            res = (
                self._sheets()
                .spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=a1_range, valueRenderOption="UNFORMATTED_VALUE")
                .execute()
            )
        except SheetsError:
            raise
        except Exception as e:
            raise _http_error(e)
        return [[str(c) for c in r] for r in res.get("values") or []]
