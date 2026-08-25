import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import SessionRow, as_utc


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
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        return None
    return row


def revoke_all_for_user(db: Session, user_id: str) -> int:
    """Every live session for one account. A password change must not leave whoever
    knew the old one still signed in."""
    rows = db.execute(select(SessionRow).where(SessionRow.user_id == user_id,
                                               SessionRow.revoked_at.is_(None))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    db.commit()
    return len(rows)


def revoke_session(db: Session, token: str) -> None:
    row = db.execute(select(SessionRow).where(SessionRow.token_hash == _hash(token))).scalar_one_or_none()
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
