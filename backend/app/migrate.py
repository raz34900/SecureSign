"""Additive schema repair for a database created by an earlier version.

`Base.metadata.create_all` creates missing tables but never alters an existing one, so a
column added to a model is simply absent from a database that predates it and every query
touching it fails. This adds what is missing and nothing else: no drops, no type changes,
no data movement. Anything beyond that belongs in a real migration tool.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("securesign")

# table -> column -> DDL type. Additive only, and every column must be nullable, because
# an existing row has no value to put in it.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "verifications": {"query_image_path": "VARCHAR(255)",
                      "query_image_encrypted": "BLOB"},
    "reference_signatures": {"image_encrypted": "BLOB"},
}


def apply(engine: Engine) -> list[str]:
    """Add any missing column. Returns what was added, for logging and for tests."""
    applied = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all just built it with every column present
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl_type in columns.items():
            if name in present:
                continue
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
            applied.append(f"{table}.{name}")
    if applied:
        log.info("schema updated: added %s", ", ".join(applied))
    return applied
