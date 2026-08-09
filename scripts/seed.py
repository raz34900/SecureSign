"""Idempotent seed: operator + one financial org + one subscriber org, one user each.
Passwords come from SS_SEED_* env vars - never hardcoded."""
import os
import sys

from sqlalchemy import select

from backend.app.auth.passwords import hash_password
from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app import models_db  # noqa: F401
from backend.app.models_db import Organisation, User

SEED = [
    ("SecureSign Ltd", "operator", "eng1", "engineer", "SS_SEED_ENGINEER_PASSWORD"),
    ("Bank A", "financial", "clerk1", "clerk", "SS_SEED_CLERK_PASSWORD"),
    ("Shop B", "subscriber", "rep1", "verifier", "SS_SEED_VERIFIER_PASSWORD"),
]


def main() -> None:
    passwords = {}
    for _, _, _, _, env in SEED:
        value = os.environ.get(env, "")
        if not value:
            sys.exit(f"error: {env} is not set")
        passwords[env] = value

    engine = make_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        for org_name, org_type, username, role, env in SEED:
            org = db.execute(select(Organisation).where(Organisation.name == org_name)).scalar_one_or_none()
            if org is None:
                org = Organisation(name=org_name, type=org_type)
                db.add(org)
                db.flush()
            user = db.execute(select(User).where(User.org_id == org.id,
                                                 User.username == username)).scalar_one_or_none()
            if user is None:
                db.add(User(org_id=org.id, username=username,
                            password_hash=hash_password(passwords[env]), role=role))
        db.commit()
    print("seeded: 3 organisations, 3 users")


if __name__ == "__main__":
    main()
