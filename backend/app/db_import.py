"""Copy a WorkFlowOS SQLite database into the configured database (normally Postgres).

    python -m app.cli db import-sqlite /data/workflowos.db

- The target is migrated first, then every WorkFlowOS table present in the source is copied.
- Rows whose key already exists in the target are skipped, so the import can be re-run safely
  (for example after an interruption) and never overwrites newer data.
- Encrypted integration credentials are copied byte for byte. They stay readable as long as the
  same encryption key (WORKFLOWOS_SECRET_KEY or the key file) is used, so Gmail stays connected.
- Afterwards each table is checked: every source row must exist in the target.
- The source file is only read, never modified.
"""

from dataclasses import dataclass
import os
from typing import Dict, List, Optional

from sqlalchemy import func, inspect, select, text

from app import db, migrate

BATCH_SIZE = 500


class ImportErrorReport(Exception):
    """The import could not run or did not copy everything; the message says what to do."""


@dataclass
class TableReport:
    table: str
    source_rows: int
    copied: int
    already_present: int
    target_rows: int


def _key_columns(table) -> List[str]:
    return [c.name for c in table.primary_key.columns]


def import_sqlite(source_path: str, target: Optional[str] = None) -> List[TableReport]:
    if "://" in source_path:
        raise ImportErrorReport("Give the path of the SQLite file, e.g. /data/workflowos.db.")
    if not os.path.isfile(source_path):
        raise ImportErrorReport(f"No SQLite file at {source_path}.")
    source = db.sqlite_file_engine(source_path)
    dest = db.get_engine(target, create_tables=False)
    if str(dest.url) == str(source.url):
        raise ImportErrorReport(
            "Source and target are the same database. Set DATABASE_URL to the database to import into."
        )

    migrate.upgrade(target)
    source_tables = set(inspect(source).get_table_names())

    reports: List[TableReport] = []
    for table in db.metadata.sorted_tables:
        if table.name not in source_tables:
            continue
        source_cols = {c["name"] for c in inspect(source).get_columns(table.name)}
        columns = [c for c in table.columns if c.name in source_cols]
        keys = _key_columns(table)
        copied = present = total = 0

        with source.connect() as src, dest.begin() as dst:
            result = src.execution_options(yield_per=BATCH_SIZE).execute(select(*columns))
            for batch in result.partitions(BATCH_SIZE):
                for row in batch:
                    total += 1
                    if db.insert_ignore(dst, table, dict(row._mapping)):
                        copied += 1
                    else:
                        present += 1
            if dst.dialect.name == "postgresql" and table.name == "activity_events":
                # Rows were copied with their ids; move the id sequence past them.
                dst.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('activity_events', 'id'), "
                        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM activity_events), 1))"
                    )
                )

        with dest.connect() as dst:
            target_rows = dst.execute(select(func.count()).select_from(table)).scalar_one()
            missing = _missing_keys(source, dst, table, keys)
        if missing:
            raise ImportErrorReport(f"{table.name}: {missing} source row(s) are not in the target after the import.")
        reports.append(TableReport(table.name, total, copied, present, target_rows))
    return reports


def _missing_keys(source, dst_conn, table, keys: List[str]) -> int:
    """How many source primary keys are absent from the target (should be 0)."""
    key_cols = [table.c[k] for k in keys]
    with source.connect() as src:
        source_keys = {tuple(r) for r in src.execute(select(*key_cols))}
    if not source_keys:
        return 0
    target_keys = {tuple(r) for r in dst_conn.execute(select(*key_cols))}
    return len(source_keys - target_keys)


def summary(reports: List[TableReport]) -> str:
    lines = [f"{'table':32} {'source':>8} {'copied':>8} {'skipped':>8} {'target':>8}"]
    for r in reports:
        lines.append(f"{r.table:32} {r.source_rows:>8} {r.copied:>8} {r.already_present:>8} {r.target_rows:>8}")
    totals: Dict[str, int] = {
        "source": sum(r.source_rows for r in reports),
        "copied": sum(r.copied for r in reports),
        "skipped": sum(r.already_present for r in reports),
    }
    lines.append(
        f"Copied {totals['copied']} of {totals['source']} rows ({totals['skipped']} were already present). "
        "Every source row is in the target."
    )
    return "\n".join(lines)
