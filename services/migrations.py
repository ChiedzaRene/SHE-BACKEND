"""Tiny idempotent schema upgrades for columns added after the first deploy.

`Base.metadata.create_all()` creates missing tables but never adds columns to existing ones,
so new columns on old tables are added here at startup. Safe to run on every start.
"""
from sqlalchemy import inspect, text

# table -> [(column, SQL type and default)]. Literals work on both PostgreSQL and SQLite.
NEW_COLUMNS = {
    "users": [
        ("must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("token_version", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def ensure_new_columns(engine) -> list:
    """Add any missing columns from NEW_COLUMNS. Returns what it added (for logging/tests)."""
    added = []
    inspector = inspect(engine)
    for table, columns in NEW_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # create_all() will create it with the columns already in the model
        existing = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as connection:
            for name, ddl in columns:
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.append(f"{table}.{name}")
    return added
