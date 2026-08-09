"""Append-only audit log. This module exposes write and read - never update/delete."""
import json

from sqlalchemy.orm import Session

from backend.app.models_db import AuditLog


def write(db: Session, *, user_id: str | None, org_id: str | None, action: str,
          resource_type: str, resource_id: str | None, outcome: str,
          detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, org_id=org_id, action=action,
                    resource_type=resource_type, resource_id=resource_id,
                    outcome=outcome, detail=json.dumps(detail) if detail else None))
    db.commit()
