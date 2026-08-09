from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import Verification


def add(db: Session, *, customer_id: str, org_id: str, user_id: str, decision: str,
        distance: float, threshold: float, confidence: float, model_version: str) -> Verification:
    row = Verification(customer_id=customer_id, requesting_org_id=org_id,
                       requesting_user_id=user_id, decision=decision, distance=distance,
                       threshold_used=threshold, confidence=confidence,
                       model_version=model_version)
    db.add(row)
    return row


def list_for_org(db: Session, org_id: str, limit: int = 50) -> list[Verification]:
    return list(db.execute(select(Verification)
                           .where(Verification.requesting_org_id == org_id)
                           .order_by(Verification.created_at.desc())
                           .limit(limit)).scalars())
