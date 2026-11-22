"""The one Gmail change WorkFlowOS can make: add a user label to a message (gmail.add_label).

Kept apart from GmailApiClient, which stays strictly read-only. This module:
- works only when an admin opted in (Settings > Gmail > "Allow labeling") and Google granted the
  gmail.modify permission at the last Connect Gmail;
- only ever *adds* a label (`addLabelIds`), never removes one, and never sends, deletes, archives,
  moves or marks messages;
- only uses labels people created (type "user"): system labels such as TRASH, SPAM, INBOX, UNREAD
  or STARRED are never applied, because adding them would delete, move or change messages.
"""

from typing import Any, Dict, List, Optional

from app import config


class GmailLabelError(Exception):
    code = "FAILED"


class LabelingNotAllowed(GmailLabelError):
    code = "MISSING_SCOPE"


class LabelNotFound(GmailLabelError):
    code = "NOT_CONFIGURED"


def labeling_status() -> Optional[str]:
    """None when labeling may be used; otherwise what an admin has to do first."""
    from app.services.credential_store import GMAIL_OPTIONS, GMAIL_TOKEN, get_credential_store

    store = get_credential_store()
    options = store.info(GMAIL_OPTIONS)
    if not (options and options.metadata.get("allow_labels")):
        return "Labeling is off. Turn on \"Allow labeling\" in Settings > Integrations > Gmail, then reconnect Gmail."
    token = store.info(GMAIL_TOKEN)
    if not token:
        return "Gmail is not connected. Connect Gmail in Settings."
    if config.GMAIL_MODIFY_SCOPE not in (token.metadata.get("scopes") or []):
        return "Google has not granted labeling yet. Click Reconnect Gmail in Settings and allow it."
    return None


class GmailLabeler:
    """Adds user labels to messages. `service` lets tests inject a fake Gmail API resource."""

    SCOPES = [*config.GMAIL_SCOPES, config.GMAIL_MODIFY_SCOPE]

    def __init__(self, service: Optional[Any] = None, check_permission: bool = True) -> None:
        self._service = service
        self._check_permission = check_permission

    def _gmail(self) -> Any:
        if self._check_permission:
            problem = labeling_status()
            if problem:
                raise LabelingNotAllowed(problem)
        if self._service is not None:
            return self._service
        from app.services.gmail_client import GmailApiClient

        # Same saved sign-in, loaded with the granted labeling scope (the read-only client would
        # refresh it down to read-only).
        return GmailApiClient(scopes=self.SCOPES).get_service()

    def user_labels(self) -> List[Dict[str, str]]:
        res = self._gmail().users().labels().list(userId="me").execute()
        return [
            {"id": label["id"], "name": label["name"]}
            for label in res.get("labels") or []
            if label.get("type") == "user" and label.get("id") and label.get("name")
        ]

    def find_label(self, name: str) -> Dict[str, str]:
        wanted = (name or "").strip().lower()
        if not wanted:
            raise LabelNotFound("No label name given.")
        for label in self.user_labels():
            if label["name"].strip().lower() == wanted:
                return label
        raise LabelNotFound(
            f"Gmail has no label named '{name}'. Create it in Gmail first (WorkFlowOS never creates or uses system labels)."
        )

    def add_label(self, message_id: str, label_id: str) -> List[str]:
        """Add one user label; returns the message's label ids afterwards."""
        res = (
            self._gmail()
            .users()
            .messages()
            .modify(userId="me", id=message_id, body={"addLabelIds": [label_id]})
            .execute()
        )
        return list(res.get("labelIds") or [])

    def message_label_ids(self, message_id: str) -> List[str]:
        res = self._gmail().users().messages().get(userId="me", id=message_id, format="minimal").execute()
        return list(res.get("labelIds") or [])
