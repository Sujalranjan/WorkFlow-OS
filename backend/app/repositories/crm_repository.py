"""CRM SQLite Repository (Phase 15B).

Dedicated repository for customer records in the WorkFlowOS Demo CRM database.
Maintains a separate database boundary from the core workflow execution engine.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from app.models.crm import CrmCustomer

logger = logging.getLogger(__name__)

DEFAULT_CRM_DB_PATH = os.getenv("CRM_DATABASE_PATH", "crm.db")


class CrmRepository:
    """Dedicated SQLite repository managing the CRM database."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DEFAULT_CRM_DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes the CRM customer schema."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crm_customers (
                    customer_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    company TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT,
                    invoice_reference TEXT,
                    recent_attachment_sha256 TEXT,
                    custom_fields TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_email ON crm_customers(email)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_name ON crm_customers(name)")
            conn.commit()

    def _row_to_customer(self, row: sqlite3.Row) -> CrmCustomer:
        """Converts an SQLite row into a CrmCustomer model."""
        custom_fields = {}
        if row["custom_fields"]:
            try:
                custom_fields = json.loads(row["custom_fields"])
            except Exception:
                custom_fields = {}

        return CrmCustomer(
            customer_id=row["customer_id"],
            name=row["name"],
            email=row["email"],
            company=row["company"] or "",
            status=row["status"] or "ACTIVE",
            notes=row["notes"] or "",
            invoice_reference=row["invoice_reference"],
            recent_attachment_sha256=row["recent_attachment_sha256"],
            custom_fields=custom_fields,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(self, customer: CrmCustomer) -> CrmCustomer:
        """Saves or updates a customer in the CRM database."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO crm_customers (
                    customer_id, name, email, company, status, notes,
                    invoice_reference, recent_attachment_sha256, custom_fields,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    company = excluded.company,
                    status = excluded.status,
                    notes = excluded.notes,
                    invoice_reference = excluded.invoice_reference,
                    recent_attachment_sha256 = excluded.recent_attachment_sha256,
                    custom_fields = excluded.custom_fields,
                    updated_at = excluded.updated_at
                """,
                (
                    customer.customer_id,
                    customer.name,
                    customer.email,
                    customer.company,
                    customer.status,
                    customer.notes,
                    customer.invoice_reference,
                    customer.recent_attachment_sha256,
                    json.dumps(customer.custom_fields or {}),
                    customer.created_at,
                    customer.updated_at,
                ),
            )
            conn.commit()
        return customer

    def get_by_id(self, customer_id: str) -> Optional[CrmCustomer]:
        """Retrieves a customer by customer_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM crm_customers WHERE customer_id = ?",
                (customer_id.strip(),),
            )
            row = cursor.fetchone()
            return self._row_to_customer(row) if row else None

    def get_by_email(self, email: str) -> Optional[CrmCustomer]:
        """Retrieves a customer by email address (case-insensitive)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM crm_customers WHERE LOWER(email) = LOWER(?)",
                (email.strip(),),
            )
            row = cursor.fetchone()
            return self._row_to_customer(row) if row else None

    def find(
        self,
        query: Optional[str] = None,
        email: Optional[str] = None,
        limit: int = 50,
    ) -> List[CrmCustomer]:
        """Searches customer records matching query, email, name, or company."""
        with self._get_connection() as conn:
            if email and email.strip() and not (query and query.strip()):
                cursor = conn.execute(
                    "SELECT * FROM crm_customers WHERE LOWER(email) LIKE ? LIMIT ?",
                    (f"%{email.strip().lower()}%", limit),
                )
            elif query and query.strip():
                q_pattern = f"%{query.strip().lower()}%"
                e_pattern = f"%{email.strip().lower()}%" if (email and email.strip()) else q_pattern
                cursor = conn.execute(
                    """
                    SELECT * FROM crm_customers
                    WHERE LOWER(name) LIKE ?
                       OR LOWER(email) LIKE ?
                       OR LOWER(company) LIKE ?
                       OR LOWER(customer_id) LIKE ?
                       OR LOWER(invoice_reference) LIKE ?
                       OR LOWER(email) LIKE ?
                    LIMIT ?
                    """,
                    (q_pattern, q_pattern, q_pattern, q_pattern, q_pattern, e_pattern, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM crm_customers ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )

            rows = cursor.fetchall()
            return [self._row_to_customer(r) for r in rows]

    def update(self, customer_id: str, updates: Dict[str, Any]) -> Optional[CrmCustomer]:
        """Updates specific fields of an existing customer record."""
        current = self.get_by_id(customer_id)
        if not current:
            return None

        # Apply updates
        if "name" in updates and updates["name"] is not None:
            current.name = updates["name"]
        if "email" in updates and updates["email"] is not None:
            current.email = updates["email"]
        if "company" in updates and updates["company"] is not None:
            current.company = updates["company"]
        if "status" in updates and updates["status"] is not None:
            current.status = updates["status"]
        if "notes" in updates and updates["notes"] is not None:
            current.notes = updates["notes"]
        if "invoice_reference" in updates and updates["invoice_reference"] is not None:
            current.invoice_reference = updates["invoice_reference"]
        if "recent_attachment_sha256" in updates and updates["recent_attachment_sha256"] is not None:
            current.recent_attachment_sha256 = updates["recent_attachment_sha256"]
        if "custom_fields" in updates and updates["custom_fields"] is not None:
            current.custom_fields.update(updates["custom_fields"])

        current.updated_at = datetime.now(timezone.utc).isoformat()
        return self.save(current)

    def list_all(self, limit: int = 100) -> List[CrmCustomer]:
        """Returns all customer records ordered by creation date."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM crm_customers ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_customer(r) for r in cursor.fetchall()]

    def delete(self, customer_id: str) -> bool:
        """Deletes a customer by customer_id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM crm_customers WHERE customer_id = ?",
                (customer_id.strip(),),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear(self) -> None:
        """Clears all customer records."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM crm_customers")
            conn.commit()

    def seed_default_customers(self) -> List[CrmCustomer]:
        """Seeds realistic default customers matching the hackathon workflow examples."""
        default_customers = [
            CrmCustomer(
                customer_id="cust-acme-001",
                name="Acme Corporation",
                email="billing@supplier.com",
                company="Acme Supplies Ltd",
                status="PENDING_INVOICE",
                notes="Primary supplier awaiting monthly invoice processing.",
                invoice_reference="INV-2026-402",
                custom_fields={"tier": "Enterprise", "account_manager": "Sarah Connor"},
            ),
            CrmCustomer(
                customer_id="cust-bajaj-002",
                name="Bajaj General Insurance",
                email="support@bajajinsurance.com",
                company="Bajaj Allianz",
                status="ACTIVE",
                notes="Policy account 12-8456-0000016530-02.",
                invoice_reference="12-8456-0000016530-02",
                custom_fields={"policy_type": "Health/General", "tier": "Gold"},
            ),
            CrmCustomer(
                customer_id="cust-globex-003",
                name="Globex Tech",
                email="billing@globex.com",
                company="Globex Corporation",
                status="ACTIVE",
                notes="Quarterly cloud license subscriber.",
                invoice_reference="INV-GLX-880",
                custom_fields={"tier": "Standard"},
            ),
        ]
        for c in default_customers:
            self.save(c)
        return default_customers
