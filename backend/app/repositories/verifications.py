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


def list_for_org(db: Session, org_id: str, *, verdict: str | None = None,
                 customer_id: str | None = None, limit: int = 100) -> list[tuple]:
    """Rows joined to the customer and the user who ran them.

    Returns (Verification, Customer, username, ModelFeedback | None) so the caller can
    render a row a clerk can act on rather than an opaque distance.
    """
    stmt = (select(Verification, Customer, User.username, ModelFeedback)
            .join(Customer, Customer.id == Verification.customer_id)
            .join(User, User.id == Verification.requesting_user_id)
            .outerjoin(ModelFeedback, ModelFeedback.verification_id == Verification.id)
            .where(Verification.requesting_org_id == org_id)
            .order_by(Verification.created_at.desc())
            .limit(limit))
    if verdict:
        stmt = stmt.where(Verification.decision == verdict)
    if customer_id:
        stmt = stmt.where(Verification.customer_id == customer_id)
    return list(db.execute(stmt).all())


def verdict_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Verification.decision, func.count())
                      .group_by(Verification.decision)).all()
    return {decision: count for decision, count in rows}


def distance_stats(db: Session) -> list[tuple[str, float, float]]:
    """(verdict, mean distance, mean confidence) - aggregate only, never per customer."""
    return [(row[0], float(row[1]), float(row[2])) for row in db.execute(
        select(Verification.decision, func.avg(Verification.distance),
               func.avg(Verification.confidence)).group_by(Verification.decision)).all()]


def all_distances(db: Session, limit: int = 5000) -> list[float]:
    return [float(d) for d in db.execute(
        select(Verification.distance).order_by(Verification.created_at.desc())
        .limit(limit)).scalars()]
