import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import SessionRow


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str, ttl_hours: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(SessionRow(token_hash=_hash(token), user_id=user_id,
                      expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours)))
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> SessionRow | None:
    row = db.execute(select(SessionRow).where(SessionRow.token_hash == _hash(token))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    return row


def revoke_session(db: Session, token: str) -> None:
    row = db.execute(select(SessionRow).where(SessionRow.token_hash == _hash(token))).scalar_one_or_none()
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
