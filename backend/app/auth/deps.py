from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Cookie, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.sessions import resolve_session
from backend.app.errors import AppError
from backend.app.models_db import Organisation, User
from backend.app.repositories import audit


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str
    org_type: str
    role: str
    username: str


def get_current_user(db: Session = Depends(get_db),
                     session: str | None = Cookie(default=None)) -> CurrentUser:
    if not session:
        raise AppError("AUTH_REQUIRED", "Authentication required.", 401)
    row = resolve_session(db, session)
    if row is None:
        raise AppError("AUTH_INVALID", "Session is invalid or expired.", 401)
    user = db.get(User, row.user_id)
    org = db.get(Organisation, user.org_id) if user else None
    if user is None or org is None or not user.is_active or not org.is_active:
        raise AppError("AUTH_INVALID", "Session is invalid or expired.", 401)
    return CurrentUser(user_id=user.id, org_id=org.id, org_type=org.type,
                       role=user.role, username=user.username)


def require_roles(*roles: str):
    def guard(user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)) -> CurrentUser:
        if user.role not in roles:
            audit.write(db, user_id=user.user_id, org_id=user.org_id,
                        action="access", resource_type="endpoint", resource_id=None,
                        outcome="denied", detail={"required_roles": list(roles), "role": user.role})
            raise AppError("FORBIDDEN", "You are not authorised for this operation.", 403)
        return user
    return guard
