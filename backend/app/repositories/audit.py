"""Append-only audit log. This module exposes write and read - never update/delete."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import AuditLog


def write(db: Session, *, user_id: str | None, org_id: str | None, action: str,
          resource_type: str, resource_id: str | None, outcome: str,
          detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, org_id=org_id, action=action,
                    resource_type=resource_type, resource_id=resource_id,
                    outcome=outcome, detail=json.dumps(detail) if detail else None))
    db.commit()


def by(db: Session, user, action: str, resource_type: str,
       resource_id: str | None = None, **detail) -> None:
    """The common case: an allowed action by a signed-in user, in one line."""
    write(db, user_id=user.user_id, org_id=user.org_id, action=action,
          resource_type=resource_type, resource_id=resource_id, outcome="allowed",
          detail=detail or None)


def latest(db: Session, *, action: str, resource_id: str) -> dict | None:
    """The most recent entry for one resource, with its detail decoded.

    Reading the log is how a recorded fact is played back without copying it onto the
    row it describes. Nothing here writes; the log stays append-only.
    """
    row = db.execute(select(AuditLog)
                     .where(AuditLog.action == action, AuditLog.resource_id == resource_id)
                     .order_by(AuditLog.at.desc(), AuditLog.id.desc())
                     .limit(1)).scalar_one_or_none()
    if row is None:
        return None
    return {"at": row.at, "user_id": row.user_id,
            "detail": json.loads(row.detail) if row.detail else {}}
