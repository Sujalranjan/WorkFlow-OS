"""Workflow version history (workflow editor).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _doc():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("workflow_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("changes", _doc(), nullable=False),
        sa.Column("spec_json", _doc(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_versions")
