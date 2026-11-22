"""Gmail and Slack connection settings (Settings page)."""

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import config
from app.security import current_actor
from app.services.integrations import IntegrationError, get_integration_service

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class GmailClientRequest(BaseModel):
    client_id: str = Field(..., min_length=10, max_length=300)
    client_secret: str = Field(..., min_length=1, max_length=300)


class GmailConnectRequest(BaseModel):
    return_to: Optional[str] = Field(default=None, description="Dashboard origin to come back to after sign-in")


class GmailConnectResponse(BaseModel):
    authorization_url: str


class HubSpotTokenRequest(BaseModel):
    access_token: str = Field(..., min_length=20, max_length=500)


class HubSpotSettingsRequest(BaseModel):
    status_property: str = Field(..., min_length=1, max_length=200)
    status_value: Optional[str] = Field(default=None, max_length=500)


class SlackSettingsRequest(BaseModel):
    # Omitted when only the channel changes: the saved token is kept.
    bot_token: Optional[str] = Field(default=None, min_length=10, max_length=300)
    channel_id: str = Field(..., min_length=2, max_length=80)


class GmailOptionsRequest(BaseModel):
    allow_labels: Optional[bool] = None
    allow_sheets: Optional[bool] = None


class SheetRequest(BaseModel):
    spreadsheet: str = Field(..., min_length=10, max_length=500)  # link or id
    sheet: str = Field(default="", max_length=100)
    columns: List[str] = Field(..., min_length=1, max_length=20)


class SharedFolderRequest(BaseModel):
    folder: str = Field(..., min_length=1, max_length=1000)


class SlackAlertsRequest(BaseModel):
    channel_id: Optional[str] = Field(default=None, max_length=80)
    notify_pending: bool = True


class SlackChannelsRequest(BaseModel):
    # A token being set up (POST body, never a URL), or omitted to use the saved one.
    bot_token: Optional[str] = Field(default=None, min_length=10, max_length=300)


def _bad_request(e: IntegrationError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("")
def describe_integrations() -> Dict[str, Any]:
    return get_integration_service().describe()


@router.put("/gmail/client")
def save_gmail_client(req: GmailClientRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_gmail_client(req.client_id, req.client_secret, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.delete("/gmail/client")
def remove_gmail_client() -> Dict[str, Any]:
    service = get_integration_service()
    service.remove_gmail_client()
    return service.describe()


@router.post("/gmail/connect", response_model=GmailConnectResponse)
def connect_gmail(req: GmailConnectRequest = GmailConnectRequest(), actor: str = Depends(current_actor)) -> GmailConnectResponse:
    try:
        url = get_integration_service().start_gmail_connect(actor, req.return_to)
    except IntegrationError as e:
        raise _bad_request(e)
    return GmailConnectResponse(authorization_url=url)


@router.get("/gmail/callback", include_in_schema=False)
def gmail_callback(
    state: str = Query(default=""),
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> RedirectResponse:
    """Google redirects the browser here. Public route: the single-use `state` authenticates it."""
    fallback = config.FRONTEND_ORIGINS[0] if config.FRONTEND_ORIGINS else ""
    try:
        return_to, _ = get_integration_service().finish_gmail_connect(state, code, error)
        target = f"{return_to or fallback}/#/settings/gmail-connected"
    except IntegrationError as e:
        target = f"{e.return_to or fallback}/#/settings/gmail-error/{quote(e.code)}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.put("/gmail/options")
def save_gmail_options(req: GmailOptionsRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    service.set_gmail_options(req.allow_labels, actor, allow_sheets=req.allow_sheets)
    return service.describe()


@router.put("/sheets")
def save_sheet(req: SheetRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_sheet(req.spreadsheet, req.sheet, req.columns, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.delete("/sheets")
def remove_sheet() -> Dict[str, Any]:
    service = get_integration_service()
    service.remove_sheet()
    return service.describe()


@router.delete("/gmail")
def disconnect_gmail() -> Dict[str, Any]:
    service = get_integration_service()
    service.disconnect_gmail()
    return service.describe()


@router.put("/slack")
def save_slack(req: SlackSettingsRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_slack(req.bot_token, req.channel_id, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.post("/slack/channels")
def list_slack_channels(req: SlackChannelsRequest) -> Dict[str, Any]:
    try:
        return get_integration_service().slack_channels(req.bot_token)
    except IntegrationError as e:
        raise _bad_request(e)


@router.put("/slack/alerts")
def save_slack_alerts(req: SlackAlertsRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_slack_alerts(req.channel_id, req.notify_pending, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.delete("/slack")
def remove_slack() -> Dict[str, Any]:
    service = get_integration_service()
    service.remove_slack()
    return service.describe()


@router.put("/files")
def save_shared_folder(req: SharedFolderRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_shared_folder(req.folder, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.delete("/files")
def remove_shared_folder() -> Dict[str, Any]:
    service = get_integration_service()
    service.remove_shared_folder()
    return service.describe()


@router.put("/hubspot")
def save_hubspot(req: HubSpotTokenRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_hubspot(req.access_token, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.get("/hubspot/properties")
def hubspot_properties() -> List[Dict[str, Any]]:
    try:
        return get_integration_service().hubspot_properties()
    except IntegrationError as e:
        raise _bad_request(e)


@router.put("/hubspot/settings")
def save_hubspot_settings(req: HubSpotSettingsRequest, actor: str = Depends(current_actor)) -> Dict[str, Any]:
    service = get_integration_service()
    try:
        service.save_hubspot_settings(req.status_property, req.status_value, actor)
    except IntegrationError as e:
        raise _bad_request(e)
    return service.describe()


@router.delete("/hubspot")
def remove_hubspot() -> Dict[str, Any]:
    service = get_integration_service()
    service.remove_hubspot()
    return service.describe()
