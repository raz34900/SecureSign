from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool

from backend.app import models_db  # noqa: F401  (registers tables)
from backend.app.db import Base, make_engine


def test_all_tables_created():
    engine = make_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "organisations", "users", "customers", "consent_records",
        "reference_signatures", "verifications", "audit_log",
        "model_feedback", "sessions", "customer_keys",
    }


def test_customer_blind_index_unique():
    engine = make_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("customers")}
    assert {"id", "national_id_encrypted", "national_id_index", "full_name",
            "enrolled_by_org_id", "status", "created_at"} <= cols
    uniques = [u["column_names"] for u in inspect(engine).get_unique_constraints("customers")]
    assert ["national_id_index"] in uniques
