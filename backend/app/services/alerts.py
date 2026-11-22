"""Operational alerts to a Slack channel: things a person has to look at.

Sent (only when an alert channel is chosen in Settings > Slack, or ALERT_SLACK_CHANNEL is set):
- a job stopped while it may have changed external systems ("needs attention");
- an email-triggered run failed or was blocked;
- an email trigger started failing to check Gmail (once, when it goes from working to failing);
- optionally, new emails are waiting for run approval.

Alerts name the workflow or trigger and link to the dashboard; they never include email contents,
credentials or personal data. Sending never raises: a Slack outage must not break the worker.
"""

import logging
from typing import Optional, Tuple

from app import config

logger = logging.getLogger(__name__)


def alert_settings() -> Tuple[Optional[str], bool]:
    """(alert channel id or None, whether to also notify about runs waiting for approval)."""
    try:
        from app.services.credential_store import SLACK, get_credential_store

        info = get_credential_store().info(SLACK)
    except Exception:  # noqa: BLE001
        info = None
    meta = info.metadata if info else {}
    channel = meta.get("alert_channel_id") or config.ALERT_SLACK_CHANNEL or None
    return channel, bool(meta.get("alert_on_pending", True))


def _dashboard(path: str = "") -> str:
    base = (config.FRONTEND_ORIGINS[0] if config.FRONTEND_ORIGINS else "").rstrip("/")
    return f"{base}/#{path}" if base else ""


def send_alert(text: str, client=None) -> bool:
    channel, _ = alert_settings()
    if not channel:
        return False
    try:
        from app.services.slack_client import SlackApiClient

        slack = client or SlackApiClient(timeout=5.0)
        slack.send_notification(channel=channel, text=f":warning: WorkFlowOS: {text}")
        return True
    except Exception as e:  # noqa: BLE001 - alerting must never break the caller
        logger.warning("Could not send alert to Slack: %s", type(e).__name__)
        return False


def job_needs_attention(kind: str, job_id: str, error: Optional[str]) -> None:
    send_alert(
        f"a background job ({kind}) stopped while it may have changed external systems and needs a person to "
        f"check it. Error: {(error or 'interrupted')[:300]}. {_dashboard('system')}"
    )


def run_problem(workflow_title: str, run_id: str, status: str, error: Optional[str]) -> None:
    send_alert(
        f"the email-triggered run of '{workflow_title}' ended {status.lower()}: {(error or 'no details')[:300]} "
        f"{_dashboard('inbox')}"
    )


def trigger_failing(trigger_name: str, error: str) -> None:
    send_alert(f"the email trigger '{trigger_name}' cannot check Gmail: {error[:300]} {_dashboard('automations')}")


def runs_waiting(trigger_name: str, count: int) -> None:
    _, notify = alert_settings()
    if notify and count:
        send_alert(f"{count} new email(s) from '{trigger_name}' are waiting for run approval. {_dashboard('inbox')}")
