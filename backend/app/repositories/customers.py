"""Customer reads/writes. Every read is scoped; the blind-index lookup exists
solely for verify + duplicate checks and returns the row, never a listing."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import Customer


def find_by_blind_index(db: Session, index: str) -> Customer | None:
    return db.execute(select(Customer).where(Customer.national_id_index == index,
                                             Customer.status == "active")).scalar_one_or_none()


def get_active(db: Session, customer_id: str) -> Customer | None:
    """Unscoped by org — callers must apply their own ownership rule."""
    return db.execute(select(Customer).where(Customer.id == customer_id,
                                             Customer.status == "active")).scalar_one_or_none()


def get_scoped(db: Session, customer_id: str, org_id: str) -> Customer | None:
    return db.execute(select(Customer).where(Customer.id == customer_id,
                                             Customer.enrolled_by_org_id == org_id,
                                             Customer.status == "active")).scalar_one_or_none()
