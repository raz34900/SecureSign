"""Create the operator organisation and its first engineer on a fresh installation.

This is the one account that cannot be created through the application, because
creating accounts requires an account. Everything after it is made in the panel.

    python scripts/bootstrap.py

Prompts for the details and reads the password twice without echoing it. For an
unattended install, pass the details as flags and the password in the environment:

    SS_BOOTSTRAP_PASSWORD=... python scripts/bootstrap.py --no-prompt \
        --code SS00 --name "SecureSign Ltd" --username eng1

A password that arrives through the environment or a flag has already been seen by the
shell's history and the process list, so the account is flagged to require a change at
first sign-in. One typed at the prompt is private already and is not.

Refuses to run once any organisation exists. There is no second bootstrap: an
installation that is already set up must be administered through the panel, where every
change is scoped and audited.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import func, select

from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app import models_db  # noqa: F401  — registers ORM tables
from backend.app.errors import AppError
from backend.app.models_db import Organisation
from backend.app.services import accounts

DEFAULT_CODE = "SS00"
DEFAULT_NAME = "SecureSign Ltd"
DEFAULT_USERNAME = "eng1"
PASSWORD_ENV = "SS_BOOTSTRAP_PASSWORD"


def ask(prompt: str, default: str) -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer or default


def ask_password() -> str:
    """Read it twice, never echo it, and refuse anything short."""
    while True:
        first = getpass.getpass("Password: ")
        if len(first) < accounts.MIN_PASSWORD_LENGTH:
            print(f"  Too short — at least {accounts.MIN_PASSWORD_LENGTH} characters.")
            continue
        if first != getpass.getpass("Confirm password: "):
            print("  The two entries did not match.")
            continue
        return first


def already_installed(db) -> bool:
    return bool(db.execute(select(func.count()).select_from(Organisation)).scalar_one())


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first operator account.")
    parser.add_argument("--code", help=f"organisation code (default {DEFAULT_CODE})")
    parser.add_argument("--name", help=f"display name (default {DEFAULT_NAME!r})")
    parser.add_argument("--username", help=f"engineer username (default {DEFAULT_USERNAME})")
    parser.add_argument("--no-prompt", action="store_true",
                        help=f"take every value from flags and ${PASSWORD_ENV}")
    args = parser.parse_args()

    settings = get_settings()
    for key, name in ((settings.pii_enc_key, "SS_PII_ENC_KEY"),
                      (settings.pii_index_key, "SS_PII_INDEX_KEY")):
        if len(key) != 64:
            sys.exit(f"error: {name} must be a 32-byte hex string before bootstrapping")

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    with factory() as db:
        if already_installed(db):
            sys.exit("error: this installation already has organisations. Create further "
                     "accounts in the engineering panel, not with this script.")

        env_password = os.environ.get(PASSWORD_ENV, "")
        if args.no_prompt:
            code = args.code or DEFAULT_CODE
            name = args.name or DEFAULT_NAME
            username = args.username or DEFAULT_USERNAME
            password = env_password
            if not password:
                sys.exit(f"error: --no-prompt needs ${PASSWORD_ENV} to be set")
        else:
            print("Setting up a fresh SecureSign installation.\n"
                  "This creates the operator organisation and its first engineer.\n")
            code = (args.code or ask("Organisation code", DEFAULT_CODE)).upper()
            name = args.name or ask("Display name", DEFAULT_NAME)
            username = (args.username or ask("Engineer username", DEFAULT_USERNAME)).lower()
            password = env_password or ask_password()

        # Typed at the prompt it is already private; supplied any other way it is not.
        handed_over = bool(env_password)

        try:
            accounts.create_organisation(db, code=code, name=name, org_type="operator")
            accounts.create_user(db, org_code=code, username=username, role="engineer",
                                 password=password, must_change_password=handed_over)
        except AppError as err:
            sys.exit(f"error: {err.message}")

    print(f"\nCreated operator {code} ({name}) with engineer {username}.")
    if handed_over:
        print(f"The password came from ${PASSWORD_ENV}, so {username} must replace it "
              "at first sign-in.")
    print("\nThe engineering panel is internal only. On the machine running SecureSign:")
    print("  http://localhost:8081/accounts")
    print("Add the institutions and their people there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
