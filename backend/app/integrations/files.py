"""Shared folder: copy the file a run downloaded into a folder the team uses (a network share, a
synced drive, ...), chosen by an admin in Settings.

Observation: the desktop agent can watch that folder too (SHARED_FOLDER_DIRECTORY). Its file events
carry `folder_role: "shared"`, and only those count as "saved to the shared folder", so ordinary
files appearing elsewhere are never mistaken for this action.
"""

import os
from typing import Optional, Tuple

from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction, Integration
from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent, ActivityEventType
from app.models.strategy import ExecutionStrategyType

SAVE_TO_FOLDER = CatalogAction(
    action_id="files.save_to_folder",
    application="Files",
    action="save_to_folder",
    description="Copy the downloaded file into the shared folder chosen in Settings",
    executor_name="SharedFolderExecutor",
    strategy=ExecutionStrategyType.API_INTEGRATION,
    risk_level=RiskLevel.MEDIUM,
    risk_category=RiskCategory.LOCAL_CHANGE,
    risk_reason="Adds a file to the shared folder (never overwrites or deletes anything).",
    parameters=(
        CatalogParameter("source_file", "The file this run downloaded", upstream_template="{downloaded_file}"),
        CatalogParameter(
            "file_name", "Name for the copy (default: the attachment's name)", required=False, upstream_template="{filename}"
        ),
    ),
    produces=("saved_file", "saved_file_name"),
)


def classify_save(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """A file appearing in the watched shared folder (copied, moved or saved there)."""
    if evt.event_type not in (ActivityEventType.FILE_CREATED, ActivityEventType.FILE_MOVED):
        return None
    if evt.metadata.get("folder_role") != "shared":
        return None
    name = evt.metadata.get("file_name") or os.path.basename(str(evt.metadata.get("file_path") or ""))
    return ClassifiedAction(SAVE_TO_FOLDER, {"file_name": str(name)} if name else {})


def _executor():
    from app.services.executors.folder_executor import SharedFolderExecutor

    return SharedFolderExecutor()


def _verifier():
    from app.services.verifiers.folder_verifier import SharedFolderVerificationStrategy

    return SharedFolderVerificationStrategy()


def status() -> Tuple[bool, str]:
    from app.services.shared_folder import folder_status

    return folder_status()


FILES = Integration(
    key="files",
    name="Shared folder",
    role="Saves downloaded files into the team's shared folder",
    actions=(SAVE_TO_FOLDER,),
    classifiers=(classify_save,),
    executors=(_executor,),
    verifiers=(_verifier,),
    status=status,
)
