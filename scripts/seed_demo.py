"""Demo fixtures: two fictional banks, two fictional shops, and the operator.

For demonstrations and manual testing only - the organisations here do not exist. A real
installation starts with scripts/bootstrap.py, which creates only the operator, and every
institution after that is added in the engineering panel.

Idempotent. Passwords come from SS_SEED_* env vars and are never hardcoded; clerks share
the clerk password and reps share the verifier password, which is fine for fictional
accounts and would not be anywhere else.

Every role the product has is represented, including an org_admin at each kind of
institution - the role behaves differently at a bank and at a shop, because IMPLIED_ROLES
expands it to what that kind of organisation does, and a demo that omits it cannot show
the team screen at all.
"""
import os
import sys

from sqlalchemy import select

from backend.app.auth.passwords import hash_password
from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app import models_db  # noqa: F401
from backend.app.models_db import Organisation, User

ENGINEER = "SS_SEED_ENGINEER_PASSWORD"
CLERK = "SS_SEED_CLERK_PASSWORD"
VERIFIER = "SS_SEED_VERIFIER_PASSWORD"
ORG_ADMIN = "SS_SEED_ORG_ADMIN_PASSWORD"

# (code, display name, type, [(username, role, password env), ...])
SEED = [
    ("SS00", "SecureSign Ltd", "operator", [("eng1", "engineer", ENGINEER)]),
    ("BA11", "Bank A", "financial", [("clerk1", "clerk", CLERK),
                                     ("boss1", "org_admin", ORG_ADMIN)]),
    ("BB22", "Bank B", "financial", [("clerk2", "clerk", CLERK)]),
    ("SA33", "Shop A", "subscriber", [("rep2", "verifier", VERIFIER)]),
    ("SB44", "Shop B", "subscriber", [("rep1", "verifier", VERIFIER),
                                      ("boss2", "org_admin", ORG_ADMIN)]),
]


def main() -> None:
    passwords = {}
    for env in {env for *_, people in SEED for _, _, env in people}:
        value = os.environ.get(env, "")
        if not value:
            sys.exit(f"error: {env} is not set")
        passwords[env] = value

    engine = make_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    added = 0
    with factory() as db:
        for code, org_name, org_type, people in SEED:
            org = db.execute(select(Organisation).where(Organisation.code == code)).scalar_one_or_none()
            if org is None:
                org = Organisation(code=code, name=org_name, type=org_type)
                db.add(org)
                db.flush()
            for username, role, env in people:
                user = db.execute(select(User).where(User.org_id == org.id,
                                                     User.username == username)).scalar_one_or_none()
                if user is None:
                    # Seeded accounts open straight into the product. A real account starts
                    # with must_change_password set, and these exist to be signed into.
                    db.add(User(org_id=org.id, username=username,
                                password_hash=hash_password(passwords[env]), role=role))
                    added += 1
        db.commit()
    total = sum(len(people) for *_, people in SEED)
    print(f"seeded: {len(SEED)} organisations, {total} users ({added} created now)")


if __name__ == "__main__":
    main()
