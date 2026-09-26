"""Normalized Gmail API Models (Phase 12).

Defines:
- GmailMessageSummary: Normalized, privacy-preserving email metadata.
- GmailSearchResult: Normalized query results payload.
"""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class GmailMessageSummary(BaseModel):
    """Privacy-preserving normalized summary of a single Gmail message.

    Stores only minimal metadata needed for search verification.
    Does NOT store full email bodies or attachments.
    """
    message_id: str = Field(..., description="Unique Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread ID")
    subject: Optional[str] = Field(default=None, description="Email subject header")
    sender: Optional[str] = Field(default=None, description="Email sender From header")
    timestamp: Optional[str] = Field(default=None, description="Internal message timestamp or Date header")
    snippet: Optional[str] = Field(default=None, description="Brief preview snippet")


class GmailSearchResult(BaseModel):
    """Structured response payload for a read-only search_email operation."""
    query: str = Field(..., description="Search query executed")
    total_found: int = Field(default=0, description="Total matching messages retrieved")
    messages: List[GmailMessageSummary] = Field(default_factory=list)
    searched_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of search execution",
    )
