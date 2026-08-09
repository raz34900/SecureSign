from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import sessions
from backend.app.auth.deps import CurrentUser, get_current_user, get_db
from backend.app.auth.passwords import verify_password
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import Organisation, User

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC = "Invalid credentials."


class LoginRequest(BaseModel):
    org_name: str
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    org = db.execute(select(Organisation).where(Organisation.name == body.org_name)).scalar_one_or_none()
    user = None
    if org is not None and org.is_active:
        user = db.execute(select(User).where(User.org_id == org.id,
                                             User.username == body.username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise AppError("AUTH_INVALID", _GENERIC, 401)
    token = sessions.create_session(db, user.id, get_settings().session_ttl_hours)
    response.set_cookie("session", token, httponly=True, samesite="lax")
    return {"role": user.role, "org_type": org.type}


@router.post("/logout")
def logout(response: Response, db: Session = Depends(get_db),
           session: str | None = Cookie(default=None)) -> dict:
    if session:
        sessions.revoke_session(db, session)
    response.delete_cookie("session")
    return {"status": "ok"}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"username": user.username, "role": user.role, "org_type": user.org_type}
