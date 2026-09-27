"""CRM REST API Endpoints (Phase 15B).

Provides a dedicated REST API surface for the WorkFlowOS Demo CRM application.
Maintains a separate application boundary from the core workflow engine.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.crm import (
    CrmCustomer,
    CrmCustomerCreate,
    CrmCustomerUpdate,
    CrmSearchResult,
)
from app.repositories.crm_repository import CrmRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["Demo CRM"])


class CrmSearchRequest(BaseModel):
    """Payload for POST /api/crm/customers/search."""
    query: Optional[str] = None
    email: Optional[str] = None
    limit: Optional[int] = 50


@router.get("/health")
def crm_health() -> Dict[str, Any]:
    """Health check endpoint for the CRM API service."""
    return {
        "status": "ok",
        "service": "WorkFlowOS Demo CRM API",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/customers", response_model=List[CrmCustomer])
def list_or_find_customers(
    query: Optional[str] = Query(default=None, description="Search filter for name, email, company, ID"),
    email: Optional[str] = Query(default=None, description="Exact or partial email filter"),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[CrmCustomer]:
    """Lists customers or filters by query/email parameters."""
    repo = CrmRepository()
    return repo.find(query=query, email=email, limit=limit)


@router.post("/customers/search", response_model=CrmSearchResult)
def search_customers(req: CrmSearchRequest) -> CrmSearchResult:
    """Structured customer search endpoint used by CRM API clients."""
    repo = CrmRepository()
    matched = repo.find(query=req.query, email=req.email, limit=req.limit or 50)
    effective_query = req.query or req.email or "all"
    return CrmSearchResult(
        query=effective_query,
        total_found=len(matched),
        customers=matched,
        searched_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/customers/{customer_id}", response_model=CrmCustomer)
def get_customer(customer_id: str) -> CrmCustomer:
    """Retrieves an individual customer record by customer_id."""
    repo = CrmRepository()
    customer = repo.get_by_id(customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found in CRM.",
        )
    return customer


@router.post("/customers", response_model=CrmCustomer, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CrmCustomerCreate) -> CrmCustomer:
    """Creates a new customer record."""
    repo = CrmRepository()
    cust_id = payload.customer_id or f"cust-{uuid.uuid4().hex[:8]}"

    existing = repo.get_by_id(cust_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Customer ID '{cust_id}' already exists.",
        )

    customer = CrmCustomer(
        customer_id=cust_id,
        name=payload.name,
        email=payload.email,
        company=payload.company or "",
        status=payload.status or "ACTIVE",
        notes=payload.notes or "",
        invoice_reference=payload.invoice_reference,
        custom_fields=payload.custom_fields or {},
    )
    return repo.save(customer)


@router.patch("/customers/{customer_id}", response_model=CrmCustomer)
@router.put("/customers/{customer_id}", response_model=CrmCustomer)
def update_customer(customer_id: str, updates: CrmCustomerUpdate) -> CrmCustomer:
    """Updates fields of an existing customer record."""
    repo = CrmRepository()
    update_dict = updates.model_dump(exclude_unset=True)
    updated = repo.update(customer_id, update_dict)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found in CRM.",
        )
    return updated


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: str) -> None:
    """Deletes a customer record from CRM."""
    repo = CrmRepository()
    success = repo.delete(customer_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found in CRM.",
        )


@router.post("/seed", response_model=List[CrmCustomer])
def seed_demo_customers() -> List[CrmCustomer]:
    """Seeds standard demo customer records for the hackathon storyline."""
    repo = CrmRepository()
    return repo.seed_default_customers()


@router.post("/reset", status_code=status.HTTP_200_OK)
def reset_crm_database() -> Dict[str, Any]:
    """Clears and re-seeds the CRM database with clean demo baseline records."""
    repo = CrmRepository()
    repo.clear()
    seeded = repo.seed_default_customers()
    return {
        "status": "reset_complete",
        "total_seeded": len(seeded),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
