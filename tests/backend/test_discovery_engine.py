"""Tests for Phase 3 Workflow Segmentation and Discovery Engine."""

from datetime import datetime, timedelta, timezone
from app.models.event import ActivityEventType
from app.services.workflow_discovery import WorkflowDiscoveryEngine
from app.services.workflow_segmenter import WorkflowSegmenter
from tests.fixtures.discovery_fixtures import create_test_event, generate_deterministic_dataset


def test_workflow_segmentation_inactivity_boundaries() -> None:
    """Verify that WorkflowSegmenter correctly splits events across inactivity boundaries."""
    events = generate_deterministic_dataset()
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0, min_session_events=2)
    sessions = segmenter.segment(events)

    # Dataset has 5 distinct activity clusters separated by 300s gaps
    assert len(sessions) == 5

    # Check session properties
    s1 = sessions[0]
    assert s1.event_count == 4
    assert "Gmail" in s1.applications_involved
    assert "Slack" in s1.applications_involved
    assert "inactivity gap" in s1.segmentation_reason.lower()


def test_discovery_engine_finds_repeated_pattern() -> None:
    """Verify that WorkflowDiscoveryEngine identifies recurring patterns and filters one-off sessions."""
    events = generate_deterministic_dataset()
    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=120.0)
    sessions = segmenter.segment(events)

    engine = WorkflowDiscoveryEngine(
        min_occurrences=2,
        similarity_threshold=0.70,
        incidental_applications={"whatsapp"},  # Treat whatsapp as incidental noise
    )
    candidates = engine.discover_candidates(sessions)

    # Should discover exactly 1 repeated pattern: the Customer Request Workflow (Sessions 1, 2, 3)
    # Session 4 (VS Code) only occurred once, and Session 5 (Spotify) only occurred once.
    assert len(candidates) == 1

    cand = candidates[0]
    assert cand.occurrences == 3  # Matches Session 1, Session 2, and Session 3 (noisy)
    assert cand.average_similarity_score >= 0.75
    assert len(cand.supporting_session_ids) == 3
    assert "gmail:window_focused" in cand.normalized_signature
    assert "slack:window_focused" in cand.normalized_signature

    # Verify explainability text is populated with actual metrics
    assert "Discovered across 3 sessions" in cand.evidence
    assert "%" in cand.evidence


def test_discovery_engine_distinct_workflows_not_merged() -> None:
    """Verify that two distinct repeated workflows produce separate candidates."""
    base = datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc)
    events = []

    # Workflow A (Repeat 1)
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "AppA", base))
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "AppB", base + timedelta(seconds=5)))

    # Gap
    t2 = base + timedelta(seconds=300)
    # Workflow A (Repeat 2)
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "AppA", t2))
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "AppB", t2 + timedelta(seconds=5)))

    # Gap
    t3 = t2 + timedelta(seconds=300)
    # Workflow B (Repeat 1)
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "Code", t3))
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "Terminal", t3 + timedelta(seconds=5)))

    # Gap
    t4 = t3 + timedelta(seconds=300)
    # Workflow B (Repeat 2)
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "Code", t4))
    events.append(create_test_event(ActivityEventType.WINDOW_FOCUSED, "Terminal", t4 + timedelta(seconds=5)))

    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=60.0)
    sessions = segmenter.segment(events)
    assert len(sessions) == 4

    engine = WorkflowDiscoveryEngine(min_occurrences=2, similarity_threshold=0.8)
    candidates = engine.discover_candidates(sessions)

    # Both Workflow A and Workflow B should be independently discovered
    assert len(candidates) == 2
    signatures = [c.normalized_signature for c in candidates]
    assert any("appa" in s and "appb" in s for s in signatures)
    assert any("code" in s and "terminal" in s for s in signatures)


def test_noise_does_not_become_workflow() -> None:
    """Verify that pure non-repeating noise generates 0 workflow candidates."""
    base = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        create_test_event(ActivityEventType.WINDOW_FOCUSED, "Random1", base),
        create_test_event(ActivityEventType.WINDOW_FOCUSED, "Random2", base + timedelta(seconds=5)),
        create_test_event(ActivityEventType.WINDOW_FOCUSED, "Random3", base + timedelta(seconds=300)),
        create_test_event(ActivityEventType.WINDOW_FOCUSED, "Random4", base + timedelta(seconds=305)),
    ]

    segmenter = WorkflowSegmenter(session_inactivity_timeout_seconds=60.0)
    sessions = segmenter.segment(events)

    engine = WorkflowDiscoveryEngine(min_occurrences=2)
    candidates = engine.discover_candidates(sessions)
    assert len(candidates) == 0
