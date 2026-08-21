"""Additive schema repair against a database that predates a column.

`create_all` never alters an existing table, so a column added to a model is simply
absent from an older database and every query touching it fails at runtime — after
deployment, on real data, not in the test suite.
"""
from sqlalchemy import inspect, text

from backend.app import migrate
from backend.app.db import Base, make_engine
from backend.app.models_db import Verification  # noqa: F401 — registers the table


def legacy_engine(tmp_path):
    """A database built the way an earlier version would have, minus the new column."""
    engine = make_engine(f"sqlite:///{tmp_path/'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE verifications DROP COLUMN query_image_path"))
    return engine


def columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_a_missing_column_is_added(tmp_path):
    engine = legacy_engine(tmp_path)
    assert "query_image_path" not in columns(engine, "verifications")

    assert migrate.apply(engine) == ["verifications.query_image_path"]
    assert "query_image_path" in columns(engine, "verifications")


def test_existing_rows_survive_and_read_as_empty(tmp_path):
    """An added column must be nullable: an existing row has no value to put in it."""
    engine = legacy_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO verifications (id, customer_id, requesting_org_id, "
            "requesting_user_id, decision, distance, threshold_used, confidence, "
            "model_version, created_at) VALUES ('v1','c1','o1','u1','VALID',0.1,0.4,90.0,"
            "'m1','2026-01-01 00:00:00')"))

    migrate.apply(engine)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT decision, query_image_path FROM verifications WHERE id='v1'")).one()
    assert row.decision == "VALID"
    assert row.query_image_path is None


def test_running_it_twice_changes_nothing(tmp_path):
    engine = legacy_engine(tmp_path)
    assert migrate.apply(engine) == ["verifications.query_image_path"]
    assert migrate.apply(engine) == []


def test_a_current_database_needs_no_repair(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'current.db'}")
    Base.metadata.create_all(engine)
    assert migrate.apply(engine) == []
