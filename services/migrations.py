"""Tiny idempotent schema upgrades for columns added after the first deploy.

`Base.metadata.create_all()` creates missing tables but never adds columns to existing ones,
so new columns on old tables are added here at startup. Safe to run on every start.
"""
from contextlib import contextmanager

from sqlalchemy import inspect, text


@contextmanager
def ddl_transaction(engine):
    """A transaction for schema changes that gives up instead of waiting forever.

    Adding a column needs a moment where nobody else is using the table. If the old version of the
    server is still busy with it during a deploy, wait at most 15 seconds and then fail with an error,
    rather than hanging until Render times the deploy out.
    """
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL lock_timeout = '15s'"))
            connection.execute(text("SET LOCAL statement_timeout = '120s'"))
        yield connection

# table -> [(column, SQL type and default)]. Literals work on both PostgreSQL and SQLite;
# a type spelled differently per database is a dict keyed by dialect name, with a "default".
NEW_COLUMNS = {
    "users": [
        ("must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("token_version", "INTEGER NOT NULL DEFAULT 0"),
        ("region", "VARCHAR(100)"),
    ],
    "incidents": [
        ("injured_person", "VARCHAR(150)"),
        ("action_plan", "TEXT"),
        ("incident_intake", "JSON NOT NULL DEFAULT '{}'"),
    ],
    "incident_workflows": [
        ("team_members", "JSON"),
        ("action_items", "JSON"),
        ("report_dates", "JSON"),
        ("report_revised", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ],
    "site_hours": [
        ("workers", "INTEGER"),
    ],
    "sites": [
        ("region", "VARCHAR(100)"),
        ("talks_from", "DATE"),
        ("code", "VARCHAR(12)"),
    ],
    "corrective_actions": [
        ("nc_id", "INTEGER"),
        ("control", "VARCHAR(30)"),
    ],
    "trainings": [
        ("document_name", "VARCHAR(255)"),
        ("document_type", "VARCHAR(120)"),
        ("document_size", "INTEGER"),
        ("document", {"postgresql": "BYTEA", "default": "BLOB"}),
    ],
    # proof files attached to a whole inspection report (added after the table was first created)
    "inspection_photos": [
        ("inspection_id", "INTEGER REFERENCES site_inspections(id) ON DELETE CASCADE"),
    ],
}

# Columns that were required when a table was first created and may now be empty. SQLite can't relax a
# column in place, so this is only done on PostgreSQL (SQLite databases are only used for tests).
NOW_OPTIONAL = {
    "inspection_photos": ["nc_id"],   # a report's own proof files belong to no NC
}


def ensure_new_columns(engine) -> list:
    """Add any missing columns from NEW_COLUMNS. Returns what it added (for logging/tests)."""
    added = []
    inspector = inspect(engine)
    for table, columns in NEW_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # create_all() will create it with the columns already in the model
        existing = {c["name"] for c in inspector.get_columns(table)}
        with ddl_transaction(engine) as connection:
            for name, ddl in columns:
                if isinstance(ddl, dict):  # a type that is spelled differently per database
                    ddl = ddl.get(engine.dialect.name, ddl["default"])
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.append(f"{table}.{name}")
    if engine.dialect.name == "postgresql":
        for table, columns in NOW_OPTIONAL.items():
            if not inspector.has_table(table):
                continue
            required = {c["name"] for c in inspector.get_columns(table) if not c.get("nullable", True)}
            with ddl_transaction(engine) as connection:
                for name in columns:
                    if name in required:
                        connection.execute(text(f"ALTER TABLE {table} ALTER COLUMN {name} DROP NOT NULL"))
                        added.append(f"{table}.{name} (now optional)")
    # The investigation's last stage used to be "report finalised"; closing now records everything it held.
    if inspector.has_table("incident_workflows"):
        with ddl_transaction(engine) as connection:
            moved = connection.execute(text(
                "UPDATE incident_workflows SET status = 'closed' WHERE status = 'report_finalised'")).rowcount
        if moved:
            added.append(f"incident_workflows: {moved} finalised report(s) now closed")
    return added
