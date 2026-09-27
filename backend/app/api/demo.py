"""Demo Orchestration & Synthetic Activity Seeding API (Phase 13.3).

Provides safe, controlled endpoints for seeding deterministic synthetic demo
activity events into WorkFlowOS without requiring CLI / terminal execution.

STRICT SAFETY GUARANTEES:
1. Generates synthetic demo ActivityEvents only.
2. Persists events through standard EventService and SQLite event_repository.
3. Does NOT create downstream workflow entities (Discovery, DNA, Semantic, Spec, Plan).
4. Does NOT access keyboard, clipboard, screens, Gmail, Slack, CRM, or OS processes.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.events import get_event_service
import app.api.semantic as semantic_module
from app.models.event import ActivityEvent, ActivityEventType
from app.repositories.canonical_repository import CanonicalWorkflowRepository
from app.repositories.event_repository import EventRepository
from app.repositories.execution_plan_repository import ExecutionPlanRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.verification_repository import VerificationRepository
from app.services.event_service import EventService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["Demo Orchestration"])

SUPPORTED_SCENARIOS = ["local_file_automation", "invoice_processing"]


class SeedActivityRequest(BaseModel):
    """Request payload for seeding demo activity events."""
    scenario: str = Field(
        default="local_file_automation",
        description="Demo scenario name. Supported: 'local_file_automation' (Primary Track A), 'invoice_processing' (Cross-App Safety Policy Demo)",
    )


class SeedActivityResponse(BaseModel):
    """Response returned upon successfully seeding demo activity."""
    events_created: int
    sessions_created: int
    scenario: str
    message: str


class ResetDemoResponse(BaseModel):
    """Outcome of demonstration database state reset."""
    status: str = "reset"
    events_deleted: int
    specifications_deleted: int
    plans_deleted: int
    executions_deleted: int
    verifications_deleted: int
    learning_profiles_deleted: int
    message: str



def build_invoice_processing_events(base_time: Optional[datetime] = None) -> List[ActivityEvent]:
    """Generates the standard deterministic invoice processing multi-session event trace.

    Contains 3 repeated customer request / invoice sessions (with noise and optional steps),
    plus 1 developer session and 1 noise session. Gaps between sessions are 300s to ensure
    clean temporal segmentation by WorkflowSegmenter (default timeout 120s).
    """
    if base_time is None:
        # Position events recently so they appear immediately in recent event queries
        base_time = datetime.now(timezone.utc) - timedelta(minutes=25)

    events: List[ActivityEvent] = []
    t = base_time

    # --- Session 1: Customer Rahul ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Gmail",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Rahul - Replacement Request"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "invoice_101.pdf", "file_path": "C:\\Downloads\\invoice_101.pdf"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="CRM",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "CRM - Customer Rahul"},
        )
    )
    t += timedelta(seconds=20)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Slack",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap (triggers session boundary) ---
    t += timedelta(seconds=300)

    # --- Session 2: Customer Ananya ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Gmail",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Ananya - Replacement Request"},
        )
    )
    t += timedelta(seconds=12)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "invoice_102.pdf", "file_path": "C:\\Downloads\\invoice_102.pdf"},
        )
    )
    t += timedelta(seconds=18)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="CRM",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "CRM - Customer Ananya"},
        )
    )
    t += timedelta(seconds=25)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Slack",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 3: Customer Vikram (with realistic noise + optional Excel step) ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Gmail",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Vikram - Replacement Request"},
        )
    )
    t += timedelta(seconds=5)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="WhatsApp",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Chat with Mom"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Google Chrome",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Search"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "invoice_103.pdf", "file_path": "C:\\Downloads\\invoice_103.pdf"},
        )
    )
    t += timedelta(seconds=20)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="CRM",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "CRM - Customer Vikram"},
        )
    )
    t += timedelta(seconds=22)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Microsoft Excel",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Log.xlsx"},
        )
    )
    t += timedelta(seconds=25)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Slack",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "#ops-notifications"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 4: Developer Workflow (Negative pattern) ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Visual Studio Code",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "main.py - project"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Terminal",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "PowerShell"},
        )
    )
    t += timedelta(seconds=30)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Browser",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Documentation"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 5: Isolated Noise ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Spotify",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Chill Mix"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Calculator",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Calculator"},
        )
    )

    return events


def build_local_file_automation_events(base_time: Optional[datetime] = None) -> List[ActivityEvent]:
    """Generates a deterministic local file data extraction, report generation, and archiving event trace.

    Contains 3 repeated local routine executions (with 1 optional logging step in session 3),
    plus 1 distinct developer session and 1 noise session. Gaps between sessions are 300s to ensure
    clean temporal segmentation by WorkflowSegmenter (default timeout 120s).

    Invariant steps across all 3 routine sessions:
    1. File System : FILE_OPENED      (read monthly transactions CSV)
    2. File System : FILE_CREATED     (generate reconciliation report JSON)
    3. File System : FILE_DOWNLOADED  (save archive report JSON)

    All 3 operations map directly to safe, allowlisted ControlledLocalExecutor actions inside the sandbox.
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc) - timedelta(minutes=25)

    events: List[ActivityEvent] = []
    t = base_time

    # --- Session 1: Batch Q1 ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_OPENED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "transactions_q1.csv", "file_path": "C:\\Data\\transactions_q1.csv"},
        )
    )
    t += timedelta(seconds=12)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_CREATED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "reconciliation_report_q1.json", "file_path": "C:\\Reports\\reconciliation_report_q1.json"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "archive_q1.json", "file_path": "C:\\Archive\\archive_q1.json"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 2: Batch Q2 ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_OPENED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "transactions_q2.csv", "file_path": "C:\\Data\\transactions_q2.csv"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_CREATED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "reconciliation_report_q2.json", "file_path": "C:\\Reports\\reconciliation_report_q2.json"},
        )
    )
    t += timedelta(seconds=18)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "archive_q2.json", "file_path": "C:\\Archive\\archive_q2.json"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 3: Batch Q3 (with optional scratch note logging) ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_OPENED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "transactions_q3.csv", "file_path": "C:\\Data\\transactions_q3.csv"},
        )
    )
    t += timedelta(seconds=8)
    # Optional step: auxiliary logging in Text Editor
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_OPENED,
            application="Text Editor",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "operator_notes.txt", "file_path": "C:\\Notes\\operator_notes.txt"},
        )
    )
    t += timedelta(seconds=12)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_CREATED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "reconciliation_report_q3.json", "file_path": "C:\\Reports\\reconciliation_report_q3.json"},
        )
    )
    t += timedelta(seconds=16)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.FILE_DOWNLOADED,
            application="File System",
            timestamp=t,
            source="demo_seed",
            metadata={"file_name": "archive_q3.json", "file_path": "C:\\Archive\\archive_q3.json"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 4: Developer Workflow ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="VS Code",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "reconciliation_script.py - WorkFlowOS"},
        )
    )
    t += timedelta(seconds=15)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Terminal",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "PowerShell - pytest"},
        )
    )

    # --- 300s Inactivity Gap ---
    t += timedelta(seconds=300)

    # --- Session 5: Isolated Noise ---
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Spotify",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Deep Focus"},
        )
    )
    t += timedelta(seconds=10)
    events.append(
        ActivityEvent(
            event_type=ActivityEventType.WINDOW_FOCUSED,
            application="Calculator",
            timestamp=t,
            source="demo_seed",
            metadata={"window_title": "Calculator"},
        )
    )

    return events


@router.post(
    "/seed-activity",
    response_model=SeedActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed deterministic synthetic activity events for demonstration",
)
def seed_demo_activity(
    payload: Optional[SeedActivityRequest] = None,
    service: EventService = Depends(get_event_service),
) -> SeedActivityResponse:
    """Populates the SQLite activity_events store with a multi-session event trace.

    Guarantees:
    - Only ActivityEvent records are created in storage.
    - Zero downstream workflow models (candidates, DNA, specs, plans) are created.
    - Zero external mutations or real desktop monitoring hooks are involved.
    """
    scenario = payload.scenario if payload else "local_file_automation"
    if scenario not in SUPPORTED_SCENARIOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported demo scenario '{scenario}'. Supported scenarios: {SUPPORTED_SCENARIOS}",
        )

    if scenario == "local_file_automation":
        events = build_local_file_automation_events()
    else:
        events = build_invoice_processing_events()

    created_count = 0
    for evt in events:
        service.record_event(evt)
        created_count += 1

    logger.info(f"Seeded {created_count} demo ActivityEvents for scenario '{scenario}'")

    return SeedActivityResponse(
        events_created=created_count,
        sessions_created=5,
        scenario=scenario,
        message=f"Successfully seeded {created_count} synthetic demo ActivityEvents across 5 task sessions for '{scenario}'.",
    )


@router.post(
    "/reset",
    response_model=ResetDemoResponse,
    status_code=status.HTTP_200_OK,
    summary="Safely reset application demonstration state",
)
def reset_demo_state(service: EventService = Depends(get_event_service)) -> ResetDemoResponse:
    """Safely clears all demo-generated SQLite entities and caches.

    STRICT GUARANTEES:
    - Only deletes demonstration data: activity_events, canonical_workflows,
      execution_plans, execution_records, verification runs/checks, and learning profiles/events.
    - Zero modification to credentials.json, token.json, .env, or OAuth configuration.
    - Resets semantic interpretation cache.
    """
    db_path = getattr(service.repository, "db_path", None)

    event_repo = EventRepository(db_path=db_path) if db_path else EventRepository()
    with event_repo._get_connection() as conn:
        with conn:
            cur = conn.execute("DELETE FROM activity_events")
            events_deleted = cur.rowcount

    canonical_repo = CanonicalWorkflowRepository(db_path=db_path) if db_path else CanonicalWorkflowRepository()
    with canonical_repo._get_connection() as conn:
        with conn:
            cur = conn.execute("DELETE FROM canonical_workflows")
            specs_deleted = cur.rowcount

    plan_repo = ExecutionPlanRepository(db_path=db_path) if db_path else ExecutionPlanRepository()
    with plan_repo._get_connection() as conn:
        with conn:
            cur = conn.execute("DELETE FROM execution_plans")
            plans_deleted = cur.rowcount

    exec_repo = ExecutionRepository(db_path=db_path) if db_path else ExecutionRepository()
    with exec_repo._get_connection() as conn:
        with conn:
            cur = conn.execute("DELETE FROM execution_records")
            executions_deleted = cur.rowcount

    ver_repo = VerificationRepository(db_path=db_path) if db_path else VerificationRepository()
    with ver_repo._get_connection() as conn:
        with conn:
            conn.execute("DELETE FROM verification_checks")
            cur = conn.execute("DELETE FROM workflow_verifications")
            verifications_deleted = cur.rowcount

    lrn_repo = LearningRepository(db_path=db_path) if db_path else LearningRepository()
    with lrn_repo._get_connection() as conn:
        with conn:
            conn.execute("DELETE FROM workflow_learning_events")
            cur = conn.execute("DELETE FROM workflow_reliability_profiles")
            profiles_deleted = cur.rowcount

    # Invalidate in-memory interpretations cache
    if semantic_module._semantic_engine is not None:
        semantic_module._semantic_engine._interpretations.clear()

    logger.info(
        f"Reset demo state: {events_deleted} events, {specs_deleted} specs, "
        f"{plans_deleted} plans, {executions_deleted} executions, "
        f"{verifications_deleted} verifications, {profiles_deleted} learning profiles."
    )

    return ResetDemoResponse(
        status="reset",
        events_deleted=events_deleted,
        specifications_deleted=specs_deleted,
        plans_deleted=plans_deleted,
        executions_deleted=executions_deleted,
        verifications_deleted=verifications_deleted,
        learning_profiles_deleted=profiles_deleted,
        message="Demonstration state reset successfully. OAuth configuration and credentials remain untouched.",
    )

