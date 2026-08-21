from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models_db import ModelFeedback, Organisation, User, Verification


def add(db: Session, *, verification_id: str, submitted_by: str, source: str,
        claimed_label: str, comment: str | None, model_version: str) -> ModelFeedback:
    row = ModelFeedback(verification_id=verification_id, submitted_by=submitted_by,
                        source=source, claimed_label=claimed_label, comment=comment,
                        model_version=model_version)
    db.add(row)
    return row


def for_verification(db: Session, verification_id: str) -> ModelFeedback | None:
    return db.execute(select(ModelFeedback).where(
        ModelFeedback.verification_id == verification_id)).scalars().first()


def list_with_context(db: Session, *, status: str | None = None,
                      limit: int = 200) -> list[tuple]:
    """(report, verification, reporting organisation) — never the customer behind it."""
    stmt = (select(ModelFeedback, Verification, Organisation)
            .join(User, User.id == ModelFeedback.submitted_by)
            .join(Organisation, Organisation.id == User.org_id)
            .outerjoin(Verification, Verification.id == ModelFeedback.verification_id)
            .order_by(ModelFeedback.created_at.desc())
            .limit(limit))
    if status:
        stmt = stmt.where(ModelFeedback.status == status)
    return list(db.execute(stmt).all())


def status_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(ModelFeedback.status, func.count())
                      .group_by(ModelFeedback.status)).all()
    return {status: count for status, count in rows}


def counts_by_org(db: Session) -> dict[str, dict[str, int]]:
    """Per-organisation report tally.

    An institution that files many reports and has almost none accepted is either
    misusing the system or attacking it, and that only shows up in aggregate.
    """
    rows = db.execute(select(User.org_id, ModelFeedback.status, func.count())
                      .join(User, User.id == ModelFeedback.submitted_by)
                      .group_by(User.org_id, ModelFeedback.status)).all()
    tally: dict[str, dict[str, int]] = {}
    for org_id, status, count in rows:
        tally.setdefault(org_id, {})[status] = count
    return tally
