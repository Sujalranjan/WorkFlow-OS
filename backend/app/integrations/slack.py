"""Slack: post a notification to the team channel."""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration, host_matches
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

_SLACK_HOSTS = ("app.slack.com",)
_CHANNEL_PATH_RE = re.compile(r"^/client/[^/]+/([CDG][A-Z0-9]+)")

SEND_NOTIFICATION = CatalogAction(
    action_id="slack.send_notification",
    application="Slack",
    action="send_notification",
    description="Post a status notification to the team Slack channel",
    executor_name="SlackApiExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.COMMUNICATION,
    risk_reason="Sends a message to a team channel.",
    parameters=(CatalogParameter("channel", "Slack channel id (defaults to SLACK_CHANNEL_ID)", required=False),),
    produces=("slack_ts",),
)


def classify_send(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Sending a message in the Slack web app (the channel id comes from the URL; text is never read)."""
    if evt.event_type != ActivityEventType.FORM_SUBMITTED:
        return None
    url = evt.metadata.get("url") or ""
    if not isinstance(url, str) or not host_matches(url, _SLACK_HOSTS):
        return None
    m = _CHANNEL_PATH_RE.match(urlparse(url).path)
    return ClassifiedAction(SEND_NOTIFICATION, {"channel": m.group(1)} if m else {})


def _executor():
    from app.services.executors.slack_executor import SlackApiExecutor

    return SlackApiExecutor()


def _verifier():
    from app.services.verifiers.slack_verifier import SlackVerificationStrategy

    return SlackVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.slack_client import SlackApiClient

    slack = SlackApiClient(timeout=3.0)
    if not slack._bot_token or not slack.default_channel_id:
        return False, "Not set up: add a bot token and channel in Settings."
    if slack.is_healthy():
        return True, f"Posting to channel {slack.default_channel_id}."
    return False, "Token rejected or Slack unreachable."


SLACK = Integration(
    key="slack",
    name="Slack",
    role="Notifies your team",
    actions=(SEND_NOTIFICATION,),
    classifiers=(classify_send,),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)
