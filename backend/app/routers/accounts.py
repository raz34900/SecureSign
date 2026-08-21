from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.repositories import audit
from backend.app.routers.auth import OrgCode, Username
from backend.app.services import accounts

# Account provisioning is not model engineering, but it lives behind the same door:
# creating and disabling accounts is the highest-privilege thing the system does.
# Reachability is a deployment control — public 404, internal listener on loopback only.
router = APIRouter(prefix="/admin", tags=["accounts"])

OrgName = Annotated[str, StringConstraints(min_length=2, max_length=120, strip_whitespace=True)]


class NewOrganisation(BaseModel):
    code: OrgCode
    name: OrgName
    type: Literal["financial", "subscriber", "operator"]


class NewUser(BaseModel):
    org_code: OrgCode
    username: Username
    role: Literal["clerk", "verifier", "org_admin", "engineer"]
    password: str


class ActiveFlag(BaseModel):
    is_active: bool


class NewPassword(BaseModel):
    password: str


class RenameOrganisation(BaseModel):
    name: OrgName


class ChangeRole(BaseModel):
    role: Literal["clerk", "verifier", "org_admin", "engineer"]


@router.get("/organisations")
def organisations(db: Session = Depends(get_db),
                  user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    return {"organisations": accounts.list_organisations(db)}


@router.post("/organisations")
def add_organisation(body: NewOrganisation, db: Session = Depends(get_db),
                     user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    created = accounts.create_organisation(db, code=body.code, name=body.name,
                                           org_type=body.type)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="create_organisation",
                resource_type="organisation", resource_id=body.code, outcome="allowed",
                detail={"type": body.type})
    return created


@router.post("/organisations/{code}/active")
def set_organisation_active(code: str, body: ActiveFlag, db: Session = Depends(get_db),
                            user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.set_organisation_active(db, code=code, active=body.is_active,
                                              acting_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id,
                action="set_organisation_active", resource_type="organisation",
                resource_id=code, outcome="allowed", detail={"is_active": body.is_active})
    return result


@router.post("/organisations/{code}/name")
def rename_organisation(code: str, body: RenameOrganisation, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.rename_organisation(db, code=code, name=body.name)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="rename_organisation",
                resource_type="organisation", resource_id=code, outcome="allowed",
                detail={"name": result["name"]})
    return result


@router.post("/users/{user_id}/role")
def change_role(user_id: str, body: ChangeRole, db: Session = Depends(get_db),
                user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.set_user_role(db, user_id=user_id, role=body.role,
                                    acting_user_id=user.user_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="change_role",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"from": result["previous_role"], "to": result["role"]})
    return result


@router.get("/users")
def users(db: Session = Depends(get_db),
          user: CurrentUser = Depends(require_roles("engineer")),
          q: Annotated[str | None, Query(max_length=80)] = None,
          role: Literal["clerk", "verifier", "org_admin", "engineer"] | None = None,
          limit: Annotated[int, Query(ge=1, le=accounts.MAX_PAGE)] = accounts.DEFAULT_PAGE,
          offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    """One page of accounts. `q` matches username, organisation code or organisation name."""
    return {"users": accounts.list_users(db, search=q, role=role, limit=limit, offset=offset),
            "total": accounts.count_users(db, search=q, role=role),
            "limit": limit, "offset": offset}


@router.post("/users")
def add_user(body: NewUser, db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    """The password is never echoed back, and only its hash is stored."""
    created = accounts.create_user(db, org_code=body.org_code, username=body.username,
                                   role=body.role, password=body.password)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="create_user",
                resource_type="user", resource_id=created["user_id"], outcome="allowed",
                detail={"org_code": body.org_code, "role": body.role})
    return created


@router.post("/users/{user_id}/active")
def set_user_active(user_id: str, body: ActiveFlag, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.set_user_active(db, user_id=user_id, active=body.is_active,
                                      acting_user_id=user.user_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="set_user_active",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"is_active": body.is_active})
    return result


@router.post("/users/{user_id}/password")
def reset_password(user_id: str, body: NewPassword, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.set_password(db, user_id=user_id, password=body.password)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="reset_password",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"sessions_revoked": result["sessions_revoked"]})
    return result


@router.delete("/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db),
                user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.delete_user(db, user_id=user_id, acting_user_id=user.user_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="delete_user",
                resource_type="user", resource_id=user_id, outcome="allowed",
                detail={"username": result["username"]})
    return result


@router.delete("/organisations/{code}")
def delete_organisation(code: str, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    result = accounts.delete_organisation(db, code=code, acting_org_id=user.org_id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="delete_organisation",
                resource_type="organisation", resource_id=code, outcome="allowed")
    return result
