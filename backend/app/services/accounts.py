"""Provisioning organisations and their users.

Until now the only way to create an account was re-running the seed script, which
meant a running registry could not take on a new institution without a deploy.

Two rules are load-bearing here. A role only makes sense inside certain kinds of
organisation — an engineer outside the operator would be a route into the engineering
panel for an institution. And nothing is ever deleted: customers, verifications and
audit rows all point back at these records, so accounts are deactivated instead.
"""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth import sessions
from backend.app.auth.passwords import hash_password, verify_password
from backend.app.errors import AppError
from backend.app.models_db import (ConsentRecord, Customer, ModelFeedback, Organisation,
                                   ReferenceSignature, SessionRow, User, Verification)

ORG_TYPES = ("financial", "subscriber", "operator")

# Which organisations may hold which role. The engineer entry is a security boundary,
# not a convention: the panel trusts the role alone.
ROLE_ORG_TYPES = {
    "clerk": {"financial"},
    "verifier": {"subscriber", "financial"},
    "org_admin": {"financial", "subscriber"},
    "engineer": {"operator"},
}

MIN_PASSWORD_LENGTH = 12


def _not_found() -> AppError:
    """One body for every miss. An administrator scoped to one organisation must not be
    able to learn whether an identifier belongs to another one."""
    return AppError("USER_NOT_FOUND", "User not found.", 404)


def _org_by_code(db: Session, code: str, scope_org_id: str | None = None) -> Organisation:
    org = db.execute(select(Organisation).where(Organisation.code == code)).scalar_one_or_none()
    if org is None or (scope_org_id is not None and org.id != scope_org_id):
        raise AppError("ORGANISATION_NOT_FOUND", f"No organisation with code {code}.", 404)
    return org


def _user_in_scope(db: Session, user_id: str, scope_org_id: str | None) -> User:
    user = db.get(User, user_id)
    if user is None or (scope_org_id is not None and user.org_id != scope_org_id):
        raise _not_found()
    return user


def _count(db: Session, model, *where) -> int:
    return int(db.execute(select(func.count()).select_from(model).where(*where)).scalar_one())


def list_organisations(db: Session) -> list[dict]:
    counts = dict(db.execute(select(User.org_id, func.count())
                             .where(User.is_active.is_(True))
                             .group_by(User.org_id)).all())
    rows = db.execute(select(Organisation).order_by(Organisation.code)).scalars()
    return [{"code": org.code, "name": org.name, "type": org.type,
             "is_active": org.is_active, "active_users": counts.get(org.id, 0),
             "created_at": org.created_at.isoformat()} for org in rows]


def list_users(db: Session, scope_org_id: str | None = None) -> list[dict]:
    stmt = (select(User, Organisation)
            .join(Organisation, Organisation.id == User.org_id)
            .order_by(Organisation.code, User.username))
    if scope_org_id is not None:
        stmt = stmt.where(User.org_id == scope_org_id)
    return [{"user_id": user.id, "username": user.username, "role": user.role,
             "is_active": user.is_active, "org_code": org.code, "org_name": org.name,
             "must_change_password": user.must_change_password,
             "deletable": not user_deletion_blockers(db, user.id),
             "created_at": user.created_at.isoformat()}
            for user, org in db.execute(stmt).all()]


def create_organisation(db: Session, *, code: str, name: str, org_type: str) -> dict:
    if org_type not in ORG_TYPES:
        raise AppError("INVALID_ORG_TYPE",
                       f"Organisation type must be one of: {', '.join(ORG_TYPES)}.", 422)
    org = Organisation(code=code, name=name.strip(), type=org_type)
    db.add(org)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_ORGANISATION",
                       "An organisation with this code or name already exists.", 409)
    return {"code": org.code, "name": org.name, "type": org.type, "is_active": org.is_active}


def create_user(db: Session, *, org_code: str, username: str, role: str, password: str,
                scope_org_id: str | None = None, must_change_password: bool = True) -> dict:
    allowed = ROLE_ORG_TYPES.get(role)
    if allowed is None:
        raise AppError("INVALID_ROLE",
                       f"Role must be one of: {', '.join(sorted(ROLE_ORG_TYPES))}.", 422)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError("WEAK_PASSWORD",
                       f"The password must be at least {MIN_PASSWORD_LENGTH} characters.", 422)

    org = _org_by_code(db, org_code, scope_org_id)
    if not org.is_active:
        raise AppError("ORGANISATION_INACTIVE",
                       "This organisation is deactivated and cannot take new users.", 422)
    if org.type not in allowed:
        raise AppError("ROLE_NOT_ALLOWED",
                       f"The {role} role is only valid in organisations of type "
                       f"{' or '.join(sorted(allowed))}. {org.code} is {org.type}.", 422)

    # Whoever typed this password knows it, so it is a handover token, not a credential.
    # The one exception is bootstrap, where the owner types their own at a prompt.
    user = User(org_id=org.id, username=username, role=role,
                password_hash=hash_password(password),
                must_change_password=must_change_password)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_USER",
                       f"{org.code} already has a user called {username}.", 409)
    return {"user_id": user.id, "username": user.username, "role": user.role,
            "org_code": org.code, "is_active": user.is_active,
            "must_change_password": user.must_change_password}


def set_password(db: Session, *, user_id: str, password: str,
                 scope_org_id: str | None = None) -> dict:
    """An administrator hands out a new password. The owner must replace it before the
    account does anything, and every existing session is cut."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError("WEAK_PASSWORD",
                       f"The password must be at least {MIN_PASSWORD_LENGTH} characters.", 422)
    user = _user_in_scope(db, user_id, scope_org_id)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    db.commit()
    revoked = sessions.revoke_all_for_user(db, user.id)
    return {"user_id": user.id, "username": user.username,
            "must_change_password": True, "sessions_revoked": revoked}


def change_own_password(db: Session, *, user_id: str, current_password: str,
                        new_password: str) -> dict:
    """Only the owner can clear the must-change flag, and only by proving the old one."""
    user = db.get(User, user_id)
    if user is None:
        raise _not_found()
    if not verify_password(user.password_hash, current_password):
        raise AppError("AUTH_INVALID", "The current password is not correct.", 401)
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise AppError("WEAK_PASSWORD",
                       f"The password must be at least {MIN_PASSWORD_LENGTH} characters.", 422)
    if verify_password(user.password_hash, new_password):
        raise AppError("PASSWORD_UNCHANGED",
                       "The new password must be different from the current one.", 422)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()
    return {"user_id": user.id, "must_change_password": False}


def user_deletion_blockers(db: Session, user_id: str) -> list[str]:
    """What a user has done that outlives them.

    A verification is evidence: the record of who checked a signature and when is the
    audit trail, and deleting the account behind it would erase that. Such an account
    can be disabled but not removed.
    """
    blockers = []
    verifications = _count(db, Verification, Verification.requesting_user_id == user_id)
    if verifications:
        blockers.append(f"{verifications} verification(s) on record")
    reports = _count(db, ModelFeedback, ModelFeedback.submitted_by == user_id)
    if reports:
        blockers.append(f"{reports} model report(s) submitted")
    return blockers


def organisation_deletion_blockers(db: Session, org_id: str) -> list[str]:
    checks = (
        (User, User.org_id == org_id, "user account(s)"),
        (Customer, Customer.enrolled_by_org_id == org_id, "enrolled customer(s)"),
        (ReferenceSignature, ReferenceSignature.org_id == org_id, "reference signature(s)"),
        (ConsentRecord, ConsentRecord.org_id == org_id, "consent record(s)"),
        (Verification, Verification.requesting_org_id == org_id, "verification(s)"),
    )
    blockers = []
    for model, condition, label in checks:
        count = _count(db, model, condition)
        if count:
            blockers.append(f"{count} {label}")
    return blockers


def delete_user(db: Session, *, user_id: str, acting_user_id: str,
                scope_org_id: str | None = None) -> dict:
    user = _user_in_scope(db, user_id, scope_org_id)
    if user.id == acting_user_id:
        raise AppError("CANNOT_DELETE_SELF",
                       "You cannot delete the account you are signed in with.", 422)
    if user.role == "engineer" and user.is_active and _active_engineers(db) <= 1:
        raise AppError("LAST_ENGINEER",
                       "This is the only active engineer account. Create another before "
                       "deleting this one.", 422)

    blockers = user_deletion_blockers(db, user.id)
    if blockers:
        raise AppError("USER_HAS_HISTORY",
                       f"{user.username} cannot be deleted because the account has "
                       f"{', and '.join(blockers)}. Disable it instead, which blocks "
                       "sign-in while keeping the audit trail intact.", 409)

    for row in db.execute(select(SessionRow).where(SessionRow.user_id == user.id)).scalars().all():
        db.delete(row)
    db.delete(user)
    db.commit()
    return {"deleted": user_id, "username": user.username}


def delete_organisation(db: Session, *, code: str, acting_org_id: str) -> dict:
    org = _org_by_code(db, code)
    if org.id == acting_org_id:
        raise AppError("CANNOT_DELETE_SELF", "You cannot delete your own organisation.", 422)
    if org.type == "operator":
        raise AppError("CANNOT_DELETE_OPERATOR",
                       "The operator organisation runs the registry and cannot be deleted.", 422)

    blockers = organisation_deletion_blockers(db, org.id)
    if blockers:
        raise AppError("ORGANISATION_HAS_HISTORY",
                       f"{org.code} cannot be deleted because it still has "
                       f"{', and '.join(blockers)}. Remove its users first, or disable "
                       "the organisation to block sign-in while keeping its records.", 409)
    db.delete(org)
    db.commit()
    return {"deleted": code}


def _active_engineers(db: Session) -> int:
    return int(db.execute(
        select(func.count()).select_from(User)
        .join(Organisation, Organisation.id == User.org_id)
        .where(User.role == "engineer", User.is_active.is_(True),
               Organisation.is_active.is_(True))).scalar_one())


def set_user_active(db: Session, *, user_id: str, active: bool, acting_user_id: str,
                    scope_org_id: str | None = None) -> dict:
    user = _user_in_scope(db, user_id, scope_org_id)
    if not active:
        if user.id == acting_user_id:
            raise AppError("CANNOT_DEACTIVATE_SELF",
                           "You cannot deactivate the account you are signed in with.", 422)
        # Losing the last engineer means losing the only way back into this panel.
        if user.role == "engineer" and user.is_active and _active_engineers(db) <= 1:
            raise AppError("LAST_ENGINEER",
                           "This is the only active engineer account. Create another "
                           "before deactivating this one.", 422)
    user.is_active = active
    db.commit()
    if not active:
        sessions.revoke_all_for_user(db, user.id)  # disabling must take effect now
    return {"user_id": user.id, "is_active": user.is_active}


def set_organisation_active(db: Session, *, code: str, active: bool,
                            acting_org_id: str) -> dict:
    org = _org_by_code(db, code)
    if not active:
        if org.id == acting_org_id:
            raise AppError("CANNOT_DEACTIVATE_SELF",
                           "You cannot deactivate your own organisation.", 422)
        if org.type == "operator":
            raise AppError("CANNOT_DEACTIVATE_OPERATOR",
                           "The operator organisation runs the registry and cannot be "
                           "deactivated.", 422)
    org.is_active = active
    db.commit()
    return {"code": org.code, "is_active": org.is_active}
