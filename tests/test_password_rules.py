"""Composition rules for a password its owner chooses.

Applied to `/auth/password` and nowhere else. A generated handover password is not chosen
by anyone and is judged on entropy instead — holding it to these rules would mean either
weakening the generator's alphabet or failing passwords the system issued itself.
"""
from backend.app.services.accounts import (MIN_PASSWORD_LENGTH, PASSWORD_RULES,
                                           password_shortfalls)
from conftest import login
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT = "pw123456"


def change(client, new_password: str, current: str = CURRENT):
    return client.post("/auth/password", json={"current_password": current,
                                               "new_password": new_password})


def test_each_missing_class_is_named(client, seeded):
    login(client, "BA11", "clerk1")
    cases = {
        "alllowercase1!": "an upper-case letter",
        "ALLUPPERCASE1!": "a lower-case letter",
        "NoDigitsHere!!": "a number",
        "NoSymbolsHere1": "a symbol",
    }
    for password, expected in cases.items():
        r = change(client, password)
        assert r.status_code == 422, password
        assert r.json()["error"]["code"] == "WEAK_PASSWORD"
        assert expected in r.json()["error"]["message"], password


def test_a_password_meeting_every_rule_is_accepted(client, seeded):
    login(client, "BA11", "clerk1")
    r = change(client, "Str0ng-Enough!Really")
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is False

    client.cookies.clear()
    assert login(client, "BA11", "clerk1", password="Str0ng-Enough!Really").status_code == 200


def test_length_is_still_enforced_alongside_the_classes(client, seeded):
    """All four classes in ten characters is still short. `Ab1!` satisfies every rule."""
    login(client, "BA11", "clerk1")
    r = change(client, "Ab1!Ab1!")
    assert r.status_code == 422
    assert f"at least {MIN_PASSWORD_LENGTH} characters" in r.json()["error"]["message"]


def test_the_shortfalls_are_reported_together(client, seeded):
    """One round trip should tell the owner everything that is wrong, not the first
    thing that is wrong."""
    missing = password_shortfalls("abc")
    assert len(missing) == 4
    assert "at least 12 characters" in missing


def test_a_generated_handover_password_is_not_held_to_these_rules(client, seeded):
    """It has no upper case and no symbol beyond the grouping dash, by design. Judging it
    by composition would force a worse alphabet on a password nobody types twice."""
    from backend.app.auth.passwords import generate_handover_password

    issued = generate_handover_password()
    assert password_shortfalls(issued), "precondition: it would fail the owner rules"

    # And yet it works, because creation does not apply them.
    from test_engineering import enter_panel
    enter_panel(client)
    created = client.post("/admin/users", json={
        "org_code": "BA11", "username": "fresh1", "role": "clerk"}).json()
    client.cookies.clear()
    assert login(client, "BA11", "fresh1",
                 password=created["initial_password"]).status_code == 200


def test_the_interface_lists_exactly_the_rules_the_server_enforces():
    """The checklist turns green as someone types, so it has to be the same set. A rule
    added on one side and not the other either blocks a password the panel called valid,
    or promises one the server will refuse."""
    view = (REPO_ROOT / "frontend" / "src" / "views" / "ChangePasswordView.vue").read_text()
    for key, _, _ in PASSWORD_RULES:
        assert f"'{key}'" in view, f"the panel does not check {key}"
    assert "'length'" in view
    assert view.count("key: '") == len(PASSWORD_RULES) + 1, "the two rule sets differ in size"
