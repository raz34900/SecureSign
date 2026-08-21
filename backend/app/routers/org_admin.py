"""Account management inside one organisation.

Unlike the provider's panel this is reachable from the public web, because an
administrator at a bank works from the bank. Every operation is therefore pinned to the
caller's own organisation: `scope_org_id` is taken from the session, never from the
request, so there is no parameter an administrator could point at a different
institution. A user id belonging to another organisation reads as not found rather than
forbidden, so the endpoint cannot be used to discover which ids exist.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.repositories import audit
from backend.app.routers.accounts import ActiveFlag, ChangeRole
from backend.app.routers.auth import Username
from backend.app.services import accounts

router = APIRouter(prefix="/org", tags=["organisation admin"])


class NewColleague(BaseModel):
    username: Username
    # "engineer" is absent by design: that role belongs to the operator, and no
    # institution may mint an account that reaches the engineering panel.
    role: Literal["clerk", "verifier", "org_admin"]


@router.get("/users")
def users(db: Session = Depends(get_db),
          user: CurrentUser = Depends(require_roles("org_admin")),
          q: Annotated[str | None, Query(max_length=80)] = None,
          limit: Annotated[int, Query(ge=1, le=accounts.MAX_PAGE)] = accounts.DEFAULT_PAGE,
          offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    return {"organisation": {"code": user.org_code, "name": user.org_name,
                             "type": user.org_type},
            "users": accounts.list_users(db, scope_org_id=user.org_id, search=q,
                                         limit=limit, offset=offset),
            "total": accounts.count_users(db, scope_org_id=user.org_id, search=q),
            "limit": limit, "offset": offset}


@router.post("/users/{user_id}/role")
def change_role(user_id: str, body: ChangeRole, db: Session = Depends(get_db),
                user: CurrentUser = Depends(require_roles("org_admin"))) -> dict:
    """Scoped to the caller's own organisation, and never to the engineer role."""
    result = accounts.set_user_role(db, user_id=user_id, role=body.role,
                                    acting_user_id=user.user_id, scope_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="change_role",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"from": result["previous_role"], "to": result["role"]})
    return result


@router.post("/users")
def add_user(body: NewColleague, db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_roles("org_admin"))) -> dict:
    # org_code comes from the session, so a colleague can only ever land in this org.
    created = accounts.create_user(db, org_code=user.org_code, username=body.username,
                                   role=body.role,
                                   scope_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="create_user",
                resource_type="user", resource_id=created["user_id"], outcome="allowed",
                detail={"org_code": user.org_code, "role": body.role})
    return created


@router.post("/users/{user_id}/active")
def set_user_active(user_id: str, body: ActiveFlag, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("org_admin"))) -> dict:
    result = accounts.set_user_active(db, user_id=user_id, active=body.is_active,
                                      acting_user_id=user.user_id, scope_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="set_user_active",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"is_active": body.is_active})
    return result


@router.post("/users/{user_id}/password")
def reset_password(user_id: str, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require_roles("org_admin"))) -> dict:
    result = accounts.set_password(db, user_id=user_id,
                                   scope_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="reset_password",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"sessions_revoked": result["sessions_revoked"]})
    return result


@router.delete("/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db),
                user: CurrentUser = Depends(require_roles("org_admin"))) -> dict:
    result = accounts.delete_user(db, user_id=user_id, acting_user_id=user.user_id,
                                  scope_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="delete_user",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"username": result["username"]})
    return result
