import pytest

from conftest import login


def test_login_sets_cookie_and_me(client, seeded):
    r = login(client, "BA11", "clerk1")
    assert r.status_code == 200
    assert r.json() == {"role": "clerk", "org_type": "financial",
                        "must_change_password": False}
    assert "session" in client.cookies
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "clerk1"
    # The code is what you sign in with; the name exists only to be displayed.
    assert me.json()["org_code"] == "BA11"
    assert me.json()["org_name"] == "Bank A"


def test_the_display_name_is_not_a_credential(client, seeded):
    """Logging in with 'Bank A' must fail — an identifier with a space in it is exactly
    what the code column exists to replace."""
    assert login(client, "Bank A", "clerk1").status_code == 422


@pytest.mark.parametrize("org_code", ["ba11", "BA 11", "B", "BA-11", "BA11!", "B" * 13, ""])
def test_malformed_organisation_codes_are_rejected(client, seeded, org_code):
    assert login(client, org_code, "clerk1").status_code == 422


@pytest.mark.parametrize("username", ["cle rk1", "Clerk1", "cl", "clerk1;--", "-clerk", ""])
def test_malformed_usernames_are_rejected(client, seeded, username):
    assert login(client, "BA11", username).status_code == 422


def test_a_well_formed_unknown_account_still_gets_the_generic_error(client, seeded):
    """Validation must not become an oracle: a plausible username that does not exist
    fails the same way a wrong password does."""
    unknown = login(client, "BA11", "ghost")
    wrong_password = login(client, "BA11", "clerk1", password="wrong")
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_an_unknown_but_well_formed_org_code_is_not_distinguishable(client, seeded):
    assert login(client, "ZZ99", "clerk1").json() == login(client, "BA11", "ghost").json()


def test_login_bad_password_generic_message(client, seeded):
    r = login(client, "BA11", "clerk1", password="wrong")
    assert r.status_code == 401
    # generic — must not reveal whether username exists (book 6.2.1 2.a)
    assert "clerk1" not in r.json()["error"]["message"]
    r2 = login(client, "BA11", "ghost")
    assert r2.json()["error"]["message"] == r.json()["error"]["message"]


def test_me_without_session(client, seeded):
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_logout_revokes(client, seeded):
    login(client, "BA11", "clerk1")
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401
