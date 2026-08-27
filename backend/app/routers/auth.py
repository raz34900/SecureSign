from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import sessions, throttle
from backend.app.auth.deps import CurrentUser, get_current_user, get_db
from backend.app.auth.passwords import hash_password, verify_password
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import Organisation, User
from backend.app.repositories import audit

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC = "Invalid credentials."

# Verified against on the miss path so both branches cost the same. Measured here before
# the fix: 8 ms for a username that does not exist, 228 ms for one that does, which
# enumerates every account for free.
_ABSENT_ACCOUNT_HASH = hash_password("no account by that name")

# Identifiers, not labels: no spaces, no case ambiguity, nothing that changes when an
# institution rebrands. The display name lives on the organisation record instead.
OrgCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,12}$")]
Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,79}$")]


class LoginRequest(BaseModel):
    org_code: OrgCode
    username: Username
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    wait = throttle.retry_after(body.org_code, body.username)
    if wait:
        raise AppError("TOO_MANY_ATTEMPTS",
                       "Too many failed sign-in attempts for this account. "
                       f"Try again in {max(1, wait // 60)} minute(s).", 429,
                       headers={"Retry-After": str(wait)})

    org = db.execute(select(Organisation).where(Organisation.code == body.org_code)).scalar_one_or_none()
    user = None
    if org is not None and org.is_active:
        user = db.execute(select(User).where(User.org_id == org.id,
                                             User.username == body.username)).scalar_one_or_none()
    known = user is not None and user.is_active
    correct = verify_password(user.password_hash if known else _ABSENT_ACCOUNT_HASH,
                              body.password)
    if not known or not correct:
        throttle.record_failure(body.org_code, body.username)
        raise AppError("AUTH_INVALID", _GENERIC, 401)
    throttle.clear(body.org_code, body.username)
    ttl_hours = get_settings().session_ttl_hours
    token = sessions.create_session(db, user.id, ttl_hours)
    # Secure: every entrypoint is TLS and port 80 only redirects, so there is no request
    # this cookie legitimately rides in the clear. Without it a single forced plaintext
    # request to any port on this host hands over a live session.
    #
    # max_age matched to the session row, not left off. Without it this is a browser
    # session cookie, and a phone that evicts the tab in the background drops it - which
    # signed clerks out every time they left the site, while a desktop that keeps its
    # process alive never showed it. The server still decides when the session dies.
    response.set_cookie("session", token, max_age=ttl_hours * 3600,
                        httponly=True, samesite="lax", secure=True)
    return {"role": user.role, "org_type": org.type,
            "must_change_password": user.must_change_password}


@router.post("/password")
def change_password(body: ChangePasswordRequest, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    """Deliberately behind get_current_user rather than require_roles: this is the one
    thing an account with a handed-out password is still allowed to do."""
    from backend.app.services import accounts

    result = accounts.change_own_password(db, user_id=user.user_id,
                                          current_password=body.current_password,
                                          new_password=body.new_password)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="change_password",
                resource_type="user", resource_id=user.user_id, outcome="allowed")
    return result


@router.post("/logout")
def logout(response: Response, db: Session = Depends(get_db),
           session: str | None = Cookie(default=None)) -> dict:
    if session:
        sessions.revoke_session(db, session)
    response.delete_cookie("session")
    return {"status": "ok"}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"user_id": user.user_id, "username": user.username, "role": user.role,
            "org_type": user.org_type, "org_code": user.org_code, "org_name": user.org_name,
            "must_change_password": user.must_change_password}
