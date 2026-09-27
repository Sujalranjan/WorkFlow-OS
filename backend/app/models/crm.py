"""Normalized CRM Models (Phase 15B).

Defines:
- CrmCustomer: Canonical customer entity in the demo CRM.
- CrmCustomerCreate: Request payload to create a new customer record.
- CrmCustomerUpdate: Request payload to update customer fields.
- CrmSearchResult: Structured search result payload.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CrmCustomer(BaseModel):
    """Canonical customer entity in the WorkFlowOS Demo CRM.

    Maintains customer record state with audit timestamps and evidence hashes.
    """
    customer_id: str = Field(..., description="Unique customer ID (e.g. CUST-001)")
    name: str = Field(..., description="Customer or organization name")
    email: str = Field(..., description="Primary contact email address")
    company: str = Field(default="", description="Company or business name")
    status: str = Field(default="ACTIVE", description="Customer lifecycle status (e.g. ACTIVE, PENDING_INVOICE, PROCESSED)")
    notes: Optional[str] = Field(default="", description="Account notes or processing log")
    invoice_reference: Optional[str] = Field(default=None, description="Linked invoice identifier or filename")
    recent_attachment_sha256: Optional[str] = Field(default=None, description="SHA-256 hash of processed attachment")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary custom attributes")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of customer creation",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of last update",
    )


class CrmCustomerCreate(BaseModel):
    """Payload to create a new customer record."""
    customer_id: Optional[str] = Field(default=None, description="Optional explicit customer ID")
    name: str = Field(..., description="Customer or contact name")
    email: str = Field(..., description="Customer email address")
    company: Optional[str] = Field(default="", description="Company name")
    status: Optional[str] = Field(default="ACTIVE", description="Initial status")
    notes: Optional[str] = Field(default="", description="Account notes")
    invoice_reference: Optional[str] = Field(default=None, description="Linked invoice reference")
    custom_fields: Optional[Dict[str, Any]] = Field(default=None, description="Custom attributes")


class CrmCustomerUpdate(BaseModel):
    """Payload to update an existing customer record."""
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    invoice_reference: Optional[str] = None
    recent_attachment_sha256: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class CrmSearchResult(BaseModel):
    """Structured response for a customer lookup query."""
    query: str = Field(..., description="Query filter used")
    total_found: int = Field(default=0, description="Total matching customer records")
    customers: List[CrmCustomer] = Field(default_factory=list, description="List of matched customer records")
    searched_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of search execution",
    )
