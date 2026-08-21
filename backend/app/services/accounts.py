"""Provisioning organisations and their users.

Until now the only way to create an account was re-running the seed script, which
meant a running registry could not take on a new institution without a deploy.

Two rules are load-bearing here. A role only makes sense inside certain kinds of
organisation - an engineer outside the operator would be a route into the engineering
panel for an institution. And nothing is ever deleted: customers, verifications and
audit rows all point back at these records, so accounts are deactivated instead.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth import sessions
from backend.app.auth.passwords import (generate_handover_password, hash_password,
                                        verify_password)
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

# Composition rules for a password its owner chooses. Applied here and nowhere else: a
# generated handover password is not chosen by anyone and is judged on entropy instead.
#
# Worth knowing what these do and do not buy. NIST 800-63B advises against composition
# rules precisely because they herd people to `Password1!` - the four classes are
# satisfied and the result is among the first guesses anyone would make. They are kept
# because they are what an examiner expects to see, and the length floor is what is
# actually carrying the weight.
PASSWORD_RULES = (
    ("uppercase", "an upper-case letter", lambda text: any(c.isupper() for c in text)),
    ("lowercase", "a lower-case letter", lambda text: any(c.islower() for c in text)),
    ("digit", "a number", lambda text: any(c.isdigit() for c in text)),
    ("symbol", "a symbol", lambda text: any(not c.isalnum() for c in text)),
)


def password_shortfalls(password: str) -> list[str]:
    """Which rules this password fails, named the way a person would say them."""
    missing = [] if len(password) >= MIN_PASSWORD_LENGTH else [
        f"at least {MIN_PASSWORD_LENGTH} characters"]
    missing += [label for _, label, holds in PASSWORD_RULES if not holds(password)]
    return missing


DEFAULT_PAGE = 50
MAX_PAGE = 200


LIKE_ESCAPE = "\\"


def _contains(term: str) -> str:
    """A LIKE pattern matching this text literally.

    Binding the parameter stops SQL injection; it does nothing about LIKE's own
    metacharacters. Unescaped, a search for `%` is the pattern `%%%` and matches every
    row - a search box that quietly means "show me everything". Escaping also makes a
    name that genuinely contains a percent sign findable.
    """
    escaped = (term.strip().lower()
               .replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
               .replace("%", f"{LIKE_ESCAPE}%")
               .replace("_", f"{LIKE_ESCAPE}_"))
    return f"%{escaped}%"


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


def _organisation_filters(search: str | None, org_type: str | None):
    conditions = []
    if org_type:
        conditions.append(Organisation.type == org_type)
    if search:
        like = _contains(search)
        conditions.append(or_(func.lower(Organisation.code).like(like, escape=LIKE_ESCAPE),
                              func.lower(Organisation.name).like(like, escape=LIKE_ESCAPE)))
    return conditions


def count_organisations(db: Session, *, search: str | None = None,
                        org_type: str | None = None) -> int:
    return int(db.execute(select(func.count()).select_from(Organisation)
                          .where(*_organisation_filters(search, org_type))).scalar_one())


def list_organisations(db: Session, *, search: str | None = None, org_type: str | None = None,
                       limit: int = DEFAULT_PAGE, offset: int = 0) -> list[dict]:
    """One page of organisations, filtered by code, name or type.

    Paged for the same reason accounts are: each row asks the database what would block
    its deletion, so an unpaged list is five counting queries per organisation.
    """
    counts = dict(db.execute(select(User.org_id, func.count())
                             .where(User.is_active.is_(True))
                             .group_by(User.org_id)).all())
    rows = db.execute(select(Organisation)
                      .where(*_organisation_filters(search, org_type))
                      .order_by(Organisation.code)
                      .limit(limit).offset(offset)).scalars()
    out = []
    for org in rows:
        # The operator runs the registry and is never deletable, whatever it holds.
        blockers = ([] if org.type != "operator"
                    else ["the operator organisation runs the registry"])
        blockers = blockers or organisation_deletion_blockers(db, org.id)
        out.append({"code": org.code, "name": org.name, "type": org.type,
                    "is_active": org.is_active, "active_users": counts.get(org.id, 0),
                    "deletable": not blockers, "blockers": blockers,
                    "created_at": org.created_at.isoformat()})
    return out


def _user_filters(scope_org_id: str | None, search: str | None, role: str | None):
    conditions = []
    if scope_org_id is not None:
        conditions.append(User.org_id == scope_org_id)
    if role:
        conditions.append(User.role == role)
    if search:
        like = _contains(search)
        conditions.append(or_(
            func.lower(User.username).like(like, escape=LIKE_ESCAPE),
            func.lower(Organisation.code).like(like, escape=LIKE_ESCAPE),
            func.lower(Organisation.name).like(like, escape=LIKE_ESCAPE)))
    return conditions


def count_users(db: Session, scope_org_id: str | None = None, *, search: str | None = None,
                role: str | None = None) -> int:
    return int(db.execute(
        select(func.count()).select_from(User)
        .join(Organisation, Organisation.id == User.org_id)
        .where(*_user_filters(scope_org_id, search, role))).scalar_one())


def list_users(db: Session, scope_org_id: str | None = None, *, search: str | None = None,
               role: str | None = None, limit: int = DEFAULT_PAGE,
               offset: int = 0) -> list[dict]:
    """One page of accounts, filtered by username, organisation or role.

    Paged rather than complete on purpose. Beyond the response size, each row asks the
    database whether the account has history before reporting it deletable, so returning
    every user turned one page load into two queries per account.
    """
    stmt = (select(User, Organisation)
            .join(Organisation, Organisation.id == User.org_id)
            .where(*_user_filters(scope_org_id, search, role))
            .order_by(Organisation.code, User.username)
            .limit(limit).offset(offset))

    cache: dict[str, list[str]] = {}

    def blockers_for(user_id: str) -> list[str]:
        if user_id not in cache:
            cache[user_id] = user_deletion_blockers(db, user_id)
        return cache[user_id]

    return [{"user_id": user.id, "username": user.username, "role": user.role,
             "is_active": user.is_active, "org_code": org.code, "org_name": org.name,
             # Carried on the row rather than looked up against the organisation list:
             # that list is now a page, so an account whose organisation is not on the
             # current page had no type to resolve and its role picker came back empty.
             "org_type": org.type,
             "must_change_password": user.must_change_password,
             "deletable": not blockers_for(user.id), "blockers": blockers_for(user.id),
             "created_at": user.created_at.isoformat()}
            for user, org in db.execute(stmt).all()]


def rename_organisation(db: Session, *, code: str, name: str) -> dict:
    """Change the display name only.

    The code is not editable, and that is the point: it is the identifier people sign in
    with and the one written into every audit row, so changing it would lock users out
    and detach the history from the organisation that made it. A code typed wrongly is
    fixed by deleting the organisation and creating it again, which the deletion rules
    allow precisely while it still holds nothing.
    """
    org = _org_by_code(db, code)
    org.name = name.strip()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_ORGANISATION",
                       "Another organisation already uses this name.", 409)
    return {"code": org.code, "name": org.name, "type": org.type, "is_active": org.is_active}


def set_user_role(db: Session, *, user_id: str, role: str, acting_user_id: str,
                  scope_org_id: str | None = None) -> dict:
    """Promote or demote an existing account.

    Same rules as creating one - a role must suit the organisation's type - plus two the
    create path does not need: nobody changes their own role, and an organisation
    administrator cannot grant engineer, because that is the operator's own role.

    There is deliberately no last-engineer guard here, unlike delete and disable. It
    would be unreachable: engineer is the only role valid in an operator organisation, so
    every attempt to move an engineer to something else is already refused for the
    organisation's type. A branch that cannot run reads as a protection that exists.
    """
    allowed = ROLE_ORG_TYPES.get(role)
    if allowed is None:
        raise AppError("INVALID_ROLE",
                       f"Role must be one of: {', '.join(sorted(ROLE_ORG_TYPES))}.", 422)
    if scope_org_id is not None and role == "engineer":
        raise AppError("ROLE_NOT_ALLOWED",
                       "An organisation administrator cannot grant the engineer role.", 422)

    user = _user_in_scope(db, user_id, scope_org_id)
    org = db.get(Organisation, user.org_id)
    if org.type not in allowed:
        raise AppError("ROLE_NOT_ALLOWED",
                       f"The {role} role is only valid in organisations of type "
                       f"{' or '.join(sorted(allowed))}. {org.code} is {org.type}.", 422)

    if user.id == acting_user_id and user.role != role:
        raise AppError("CANNOT_CHANGE_OWN_ROLE",
                       "You cannot change the role of the account you are signed in with.",
                       422)

    previous, user.role = user.role, role
    db.commit()
    return {"user_id": user.id, "username": user.username, "role": user.role,
            "previous_role": previous, "org_code": org.code}


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


def create_user(db: Session, *, org_code: str, username: str, role: str,
                password: str | None = None, scope_org_id: str | None = None,
                must_change_password: bool = True) -> dict:
    """Create an account with a one-time password the creator did not choose.

    `password` exists for bootstrap, where the first operator types their own at a prompt
    and it is a real credential from the start. Every other path leaves it None and takes
    the generated one, which is returned once and never again.
    """
    allowed = ROLE_ORG_TYPES.get(role)
    if allowed is None:
        raise AppError("INVALID_ROLE",
                       f"Role must be one of: {', '.join(sorted(ROLE_ORG_TYPES))}.", 422)
    issued = password or generate_handover_password()
    if len(issued) < MIN_PASSWORD_LENGTH:
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
                password_hash=hash_password(issued),
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
            "must_change_password": user.must_change_password,
            "initial_password": issued}


def set_password(db: Session, *, user_id: str, scope_org_id: str | None = None) -> dict:
    """Reset to a generated one-time password. The administrator does not choose it.

    Same reasoning as creation: a reset is where a weak password gets typed, and a reset
    account sits unused in exactly the state an attacker wants. The owner must replace it
    before the account does anything, and every existing session is cut immediately.
    """
    issued = generate_handover_password()
    user = _user_in_scope(db, user_id, scope_org_id)
    user.password_hash = hash_password(issued)
    user.must_change_password = True
    db.commit()
    revoked = sessions.revoke_all_for_user(db, user.id)
    return {"user_id": user.id, "username": user.username, "must_change_password": True,
            "sessions_revoked": revoked, "initial_password": issued}


def change_own_password(db: Session, *, user_id: str, current_password: str,
                        new_password: str) -> dict:
    """Only the owner can clear the must-change flag, and only by proving the old one."""
    user = db.get(User, user_id)
    if user is None:
        raise _not_found()
    if not verify_password(user.password_hash, current_password):
        raise AppError("AUTH_INVALID", "The current password is not correct.", 401)
    missing = password_shortfalls(new_password)
    if missing:
        raise AppError("WEAK_PASSWORD",
                       f"The password still needs {', and '.join(missing)}.", 422)
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
