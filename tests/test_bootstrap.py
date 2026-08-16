"""First-run bootstrap: the one account that cannot be made through the application.

The rules that matter are that it runs exactly once, that it produces a usable engineer,
and that a password which has passed through the environment is treated as handed over
rather than private.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import bootstrap  # noqa: E402
from backend.app.models_db import Organisation, User  # noqa: E402

STRONG = "a-long-enough-password"


@pytest.fixture
def fresh(session_factory, monkeypatch):
    """An empty database, with bootstrap pointed at it instead of the configured one."""
    monkeypatch.setattr(bootstrap, "make_engine", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap.Base.metadata, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap, "make_session_factory", lambda *a, **k: session_factory)
    monkeypatch.setenv("SS_PII_ENC_KEY", "aa" * 32)
    monkeypatch.setenv("SS_PII_INDEX_KEY", "bb" * 32)
    from backend.app.config import get_settings
    get_settings.cache_clear()
    return session_factory


def run(monkeypatch, argv: list[str], password: str | None = None) -> int:
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", *argv])
    if password is not None:
        monkeypatch.setenv(bootstrap.PASSWORD_ENV, password)
    else:
        monkeypatch.delenv(bootstrap.PASSWORD_ENV, raising=False)
    return bootstrap.main()


def test_bootstrap_creates_the_operator_and_its_engineer(fresh, monkeypatch):
    assert run(monkeypatch, ["--no-prompt"], password=STRONG) == 0

    with fresh() as db:
        org = db.execute(select(Organisation)).scalar_one()
        assert (org.code, org.name, org.type) == ("SS00", "SecureSign Ltd", "operator")
        user = db.execute(select(User)).scalar_one()
        assert (user.username, user.role, user.is_active) == ("eng1", "engineer", True)


def test_a_password_from_the_environment_must_be_replaced(fresh, monkeypatch):
    """It has been through the shell's history and the process list, so it is not private."""
    run(monkeypatch, ["--no-prompt"], password=STRONG)
    with fresh() as db:
        assert db.execute(select(User)).scalar_one().must_change_password is True


def test_a_password_typed_at_the_prompt_is_already_private(fresh, monkeypatch):
    monkeypatch.setattr(bootstrap, "ask", lambda prompt, default: default)
    monkeypatch.setattr(bootstrap, "ask_password", lambda: STRONG)
    assert run(monkeypatch, []) == 0
    with fresh() as db:
        assert db.execute(select(User)).scalar_one().must_change_password is False


def test_custom_details_are_honoured(fresh, monkeypatch):
    run(monkeypatch, ["--no-prompt", "--code", "OP42", "--name", "Registry Ltd",
                      "--username", "root1"], password=STRONG)
    with fresh() as db:
        org = db.execute(select(Organisation)).scalar_one()
        assert (org.code, org.name) == ("OP42", "Registry Ltd")
        assert db.execute(select(User)).scalar_one().username == "root1"


def test_bootstrap_refuses_to_run_twice(fresh, monkeypatch):
    run(monkeypatch, ["--no-prompt"], password=STRONG)
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, ["--no-prompt", "--code", "OP99"], password=STRONG)
    assert "already has organisations" in str(exit_info.value)

    with fresh() as db:
        assert len(db.execute(select(Organisation)).scalars().all()) == 1


def test_unattended_bootstrap_needs_a_password(fresh, monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, ["--no-prompt"], password=None)
    assert bootstrap.PASSWORD_ENV in str(exit_info.value)


def test_a_weak_password_is_refused(fresh, monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, ["--no-prompt"], password="short")
    assert "12 characters" in str(exit_info.value)
    with fresh() as db:
        assert db.execute(select(User)).first() is None


def test_the_bootstrapped_engineer_can_sign_in(fresh, monkeypatch, client):
    run(monkeypatch, ["--no-prompt"], password=STRONG)
    from conftest import login

    signed_in = login(client, "SS00", "eng1", password=STRONG)
    assert signed_in.status_code == 200
    assert signed_in.json()["role"] == "engineer"
