from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models_db import Customer, ModelFeedback, User, Verification


def add(db: Session, *, customer_id: str, org_id: str, user_id: str, decision: str,
        distance: float, threshold: float, confidence: float, model_version: str) -> Verification:
    row = Verification(customer_id=customer_id, requesting_org_id=org_id,
                       requesting_user_id=user_id, decision=decision, distance=distance,
                       threshold_used=threshold, confidence=confidence,
                       model_version=model_version)
    db.add(row)
    return row


def get_for_org(db: Session, verification_id: str, org_id: str) -> Verification | None:
    return db.execute(select(Verification)
                      .where(Verification.id == verification_id,
                             Verification.requesting_org_id == org_id)).scalar_one_or_none()


def _scoped(org_id: str, verdict: str | None, customer_id: str | None):
    conditions = [Verification.requesting_org_id == org_id]
    if verdict:
        conditions.append(Verification.decision == verdict)
    if customer_id:
        conditions.append(Verification.customer_id == customer_id)
    return conditions


def count_for_org(db: Session, org_id: str, *, verdict: str | None = None,
                  customer_id: str | None = None) -> int:
    """How many rows match, regardless of the page asked for.

    Without this the caller cannot tell a full page from the end of the data, which is
    how the old fixed limit of 100 silently hid every verification past the hundredth.
    """
    return int(db.execute(select(func.count()).select_from(Verification)
                          .where(*_scoped(org_id, verdict, customer_id))).scalar_one())


def list_for_org(db: Session, org_id: str, *, verdict: str | None = None,
                 customer_id: str | None = None, limit: int = 50,
                 offset: int = 0) -> list[tuple]:
    """One page of rows, joined to the customer and the user who ran them.

    Returns (Verification, Customer, username, ModelFeedback | None) so the caller can
    render a row a clerk can act on rather than an opaque distance. Ordered by id as well
    as time so that two rows written in the same clock tick cannot swap between pages and
    hide one of themselves.
    """
    stmt = (select(Verification, Customer, User.username, ModelFeedback)
            .join(Customer, Customer.id == Verification.customer_id)
            .join(User, User.id == Verification.requesting_user_id)
            .outerjoin(ModelFeedback, ModelFeedback.verification_id == Verification.id)
            .where(*_scoped(org_id, verdict, customer_id))
            .order_by(Verification.created_at.desc(), Verification.id.desc())
            .limit(limit).offset(offset))
    return list(db.execute(stmt).all())


def verdict_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Verification.decision, func.count())
                      .group_by(Verification.decision)).all()
    return {decision: count for decision, count in rows}


def distance_stats(db: Session) -> list[tuple[str, float, float]]:
    """(verdict, mean distance, mean confidence) — aggregate only, never per customer."""
    return [(row[0], float(row[1]), float(row[2])) for row in db.execute(
        select(Verification.decision, func.avg(Verification.distance),
               func.avg(Verification.confidence)).group_by(Verification.decision)).all()]


def all_distances(db: Session, limit: int = 5000) -> list[float]:
    return [float(d) for d in db.execute(
        select(Verification.distance).order_by(Verification.created_at.desc())
        .limit(limit)).scalars()]
