"""Re-export of the recorded browser sessions used by the observation->execution tests."""

from app.services.observed_sessions import (  # noqa: F401
    GMAIL_SEARCH,
    GMAIL_SEARCH_URL,
    SESSIONS,
    SLACK_CHANNEL,
    build_observed_events,
    build_session_events,
)
