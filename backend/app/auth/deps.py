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
    org_code: str
    org_name: str
    role: str
    username: str
    must_change_password: bool = False


# An org_admin is the senior account inside its own organisation, so it can do whatever
# that kind of organisation does. It never gains "engineer": that role belongs to the
# operator and is the door to the engineering panel.
IMPLIED_ROLES = {
    "financial": frozenset({"clerk", "verifier"}),
    "subscriber": frozenset({"verifier"}),
}


def effective_roles(user: CurrentUser) -> frozenset[str]:
    if user.role != "org_admin":
        return frozenset({user.role})
    return frozenset({user.role}) | IMPLIED_ROLES.get(user.org_type, frozenset())


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
                       org_code=org.code, org_name=org.name,
                       role=user.role, username=user.username,
                       must_change_password=user.must_change_password)


def require_roles(*roles: str):
    def guard(user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)) -> CurrentUser:
        # Every real endpoint goes through here, so this is the one place that has to
        # hold the line while a handed-out password is still in force. Changing the
        # password uses get_current_user directly and stays reachable.
        if user.must_change_password:
            raise AppError("PASSWORD_CHANGE_REQUIRED",
                           "Set your own password before using the system.", 403)
        if not effective_roles(user) & set(roles):
            audit.write(db, user_id=user.user_id, org_id=user.org_id,
                        action="access", resource_type="endpoint", resource_id=None,
                        outcome="denied", detail={"required_roles": list(roles), "role": user.role})
            raise AppError("FORBIDDEN", "You are not authorised for this operation.", 403)
        return user
    return guard
