"""Baseline schema (everything up to Phase 2a).

Revision ID: 0001
Revises:
Create Date: 2026-11-17

Works on a fresh database and on databases created before migrations existed (by the old
`CREATE TABLE IF NOT EXISTS` code): existing tables and their data are kept, and only what is
missing (tables, indexes) is added. The schema is written out here rather than imported from
app.db so this revision never changes after it ships.
"""

from typing import List, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _doc():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _existing_tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_indexes(table: str) -> set:
    return {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}


def _table(existing: set, name: str, *items) -> None:
    if name not in existing:
        op.create_table(name, *items)


def _indexes(name: str, specs: List[tuple]) -> None:
    present = _existing_indexes(name)
    for index_name, columns, unique in specs:
        if index_name not in present:
            op.create_index(index_name, name, columns, unique=unique)


def upgrade() -> None:
    existing = _existing_tables()
    T, I, B, F, X = sa.Text, sa.Integer, sa.Boolean, sa.Float, sa.LargeBinary

    # observation
    _table(
        existing,
        "activity_events",
        sa.Column("id", I(), primary_key=True, autoincrement=True),
        sa.Column("event_id", T(), nullable=False, unique=True),
        sa.Column("event_type", T(), nullable=False),
        sa.Column("timestamp", T(), nullable=False),
        sa.Column("application", T()),
        sa.Column("source", T(), nullable=False),
        sa.Column("metadata", _doc(), nullable=False),
    )

    # workflows
    _table(
        existing,
        "canonical_workflows",
        sa.Column("workflow_id", T(), primary_key=True),
        sa.Column("source_dna_id", T(), nullable=False),
        sa.Column("source_semantic_workflow_id", T(), nullable=False),
        sa.Column("title", T(), nullable=False),
        sa.Column("approval_state", T(), nullable=False),
        sa.Column("overall_risk_level", T(), nullable=False),
        sa.Column("created_at", T(), nullable=False),
        sa.Column("updated_at", T(), nullable=False),
        sa.Column("spec_json", _doc(), nullable=False),
    )
    _indexes(
        "canonical_workflows",
        [
            ("ix_canonical_workflows_source_dna_id", ["source_dna_id"], False),
            ("ix_canonical_workflows_source_semantic_workflow_id", ["source_semantic_workflow_id"], False),
        ],
    )

    _table(
        existing,
        "execution_plans",
        sa.Column("plan_id", T(), primary_key=True),
        sa.Column("source_workflow_id", T(), nullable=False),
        sa.Column("status", T(), nullable=False),
        sa.Column("dry_run_status", T(), nullable=False),
        sa.Column("created_at", T(), nullable=False),
        sa.Column("updated_at", T(), nullable=False),
        sa.Column("plan_json", _doc(), nullable=False),
    )
    _indexes("execution_plans", [("ix_execution_plans_source_workflow_id", ["source_workflow_id"], False)])

    _table(
        existing,
        "execution_records",
        sa.Column("execution_id", T(), primary_key=True),
        sa.Column("workflow_id", T(), nullable=False),
        sa.Column("execution_plan_id", T(), nullable=False),
        sa.Column("idempotency_key", T()),
        sa.Column("status", T(), nullable=False),
        sa.Column("execution_mode", T(), nullable=False),
        sa.Column("start_time", T(), nullable=False),
        sa.Column("end_time", T()),
        sa.Column("record_json", _doc(), nullable=False),
    )
    _indexes(
        "execution_records",
        [
            ("ix_execution_records_workflow_id", ["workflow_id"], False),
            ("ix_execution_records_execution_plan_id", ["execution_plan_id"], False),
            ("ix_execution_records_idempotency_key", ["idempotency_key"], False),
        ],
    )

    _table(
        existing,
        "workflow_verifications",
        sa.Column("verification_run_id", T(), primary_key=True),
        sa.Column("execution_id", T(), nullable=False),
        sa.Column("workflow_id", T(), nullable=False),
        sa.Column("execution_plan_id", T(), nullable=False),
        sa.Column("overall_status", T(), nullable=False),
        sa.Column("verified_count", I(), nullable=False),
        sa.Column("failed_count", I(), nullable=False),
        sa.Column("unknown_count", I(), nullable=False),
        sa.Column("started_at", T(), nullable=False),
        sa.Column("completed_at", T()),
        sa.Column("result_json", _doc(), nullable=False),
    )
    _indexes("workflow_verifications", [("ix_workflow_verifications_execution_id", ["execution_id"], False)])

    _table(
        existing,
        "verification_checks",
        sa.Column("verification_id", T(), primary_key=True),
        sa.Column("verification_run_id", T(), nullable=False),
        sa.Column("execution_id", T(), nullable=False),
        sa.Column("planned_step_id", T(), nullable=False),
        sa.Column("status", T(), nullable=False),
        sa.Column("check_json", _doc(), nullable=False),
    )
    _indexes("verification_checks", [("ix_verification_checks_verification_run_id", ["verification_run_id"], False)])

    _table(
        existing,
        "workflow_reliability_profiles",
        sa.Column("workflow_id", T(), primary_key=True),
        sa.Column("profile_id", T(), nullable=False),
        sa.Column("total_executions", I(), nullable=False),
        sa.Column("reliability_rate", F(), nullable=False),
        sa.Column("computed_at", T(), nullable=False),
        sa.Column("profile_json", _doc(), nullable=False),
    )

    _table(
        existing,
        "workflow_learning_events",
        sa.Column("event_id", T(), primary_key=True),
        sa.Column("workflow_id", T(), nullable=False),
        sa.Column("event_type", T(), nullable=False),
        sa.Column("timestamp", T(), nullable=False),
        sa.Column("event_json", _doc(), nullable=False),
    )
    _indexes(
        "workflow_learning_events",
        [
            ("ix_workflow_learning_events_workflow_id", ["workflow_id"], False),
            ("ix_workflow_learning_events_timestamp", ["timestamp"], False),
        ],
    )

    # automation
    _table(
        existing,
        "email_triggers",
        sa.Column("trigger_id", T(), primary_key=True),
        sa.Column("workflow_id", T(), nullable=False),
        sa.Column("enabled", B(), nullable=False),
        sa.Column("created_at", T(), nullable=False),
        sa.Column("record_json", _doc(), nullable=False),
    )

    _table(
        existing,
        "workflow_runs",
        sa.Column("run_id", T(), primary_key=True),
        sa.Column("trigger_id", T(), nullable=False),
        sa.Column("workflow_id", T(), nullable=False),
        sa.Column("message_id", T(), nullable=False),
        sa.Column("status", T(), nullable=False),
        sa.Column("created_at", T(), nullable=False),
        sa.Column("record_json", _doc(), nullable=False),
        sa.UniqueConstraint("trigger_id", "message_id", name="uq_workflow_runs_trigger_message"),
    )
    _indexes("workflow_runs", [("ix_workflow_runs_status", ["status"], False)])

    # auth
    _table(
        existing,
        "users",
        sa.Column("user_id", T(), primary_key=True),
        sa.Column("email", T(), nullable=False),
        sa.Column("password_hash", T(), nullable=False),
        sa.Column("record_json", _doc(), nullable=False),
    )
    # Expression index (case-insensitive unique emails). Raw SQL because SQLAlchemy cannot reflect
    # expression indexes on SQLite; IF NOT EXISTS keeps it safe on adopted databases. Both SQLite and
    # Postgres accept this statement.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email))")

    _table(
        existing,
        "sessions",
        sa.Column("token_hash", T(), primary_key=True),
        sa.Column("user_id", T(), nullable=False),
        sa.Column("created_at", T(), nullable=False),
        sa.Column("expires_at", T(), nullable=False),
    )
    _indexes("sessions", [("ix_sessions_user_id", ["user_id"], False)])

    _table(
        existing,
        "api_keys",
        sa.Column("key_id", T(), primary_key=True),
        sa.Column("key_hash", T(), nullable=False, unique=True),
        sa.Column("record_json", _doc(), nullable=False),
    )

    # credentials
    _table(
        existing,
        "integration_credentials",
        sa.Column("name", T(), primary_key=True),
        sa.Column("ciphertext", X(), nullable=False),
        sa.Column("metadata_json", _doc(), nullable=False),
        sa.Column("updated_at", T(), nullable=False),
        sa.Column("updated_by", T()),
    )
    _table(
        existing,
        "oauth_states",
        sa.Column("state_hash", T(), primary_key=True),
        sa.Column("ciphertext", X(), nullable=False),
        sa.Column("expires_at", T(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded: it would delete every table and its data.")
