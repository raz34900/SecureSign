"""Demo fixtures: two fictional banks, two fictional shops, and the operator.

For demonstrations and manual testing only — the organisations here do not exist. A real
installation starts with scripts/bootstrap.py, which creates only the operator, and every
institution after that is added in the engineering panel.

Idempotent. Passwords come from SS_SEED_* env vars and are never hardcoded; clerks share
the clerk password and reps share the verifier password, which is fine for fictional
accounts and would not be anywhere else.
"""
import os
import sys

from sqlalchemy import select

from backend.app.auth.passwords import hash_password
from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app import models_db  # noqa: F401
from backend.app.models_db import Organisation, User

SEED = [
    ("SS00", "SecureSign Ltd", "operator", "eng1", "engineer", "SS_SEED_ENGINEER_PASSWORD"),
    ("BA11", "Bank A", "financial", "clerk1", "clerk", "SS_SEED_CLERK_PASSWORD"),
    ("BB22", "Bank B", "financial", "clerk2", "clerk", "SS_SEED_CLERK_PASSWORD"),
    ("SA33", "Shop A", "subscriber", "rep2", "verifier", "SS_SEED_VERIFIER_PASSWORD"),
    ("SB44", "Shop B", "subscriber", "rep1", "verifier", "SS_SEED_VERIFIER_PASSWORD"),
]


def main() -> None:
    passwords = {}
    for *_, env in SEED:
        value = os.environ.get(env, "")
        if not value:
            sys.exit(f"error: {env} is not set")
        passwords[env] = value

    engine = make_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        for code, org_name, org_type, username, role, env in SEED:
            org = db.execute(select(Organisation).where(Organisation.code == code)).scalar_one_or_none()
            if org is None:
                org = Organisation(code=code, name=org_name, type=org_type)
                db.add(org)
                db.flush()
            user = db.execute(select(User).where(User.org_id == org.id,
                                                 User.username == username)).scalar_one_or_none()
            if user is None:
                db.add(User(org_id=org.id, username=username,
                            password_hash=hash_password(passwords[env]), role=role))
        db.commit()
    print("seeded: 5 organisations, 5 users")


if __name__ == "__main__":
    main()
