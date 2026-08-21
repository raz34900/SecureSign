"""Correcting an account after it exists: renaming, promoting, and finding one.

Everything here was previously a delete-and-recreate, which is not available once an
organisation holds records - so a typo in a name was permanent.
"""
from conftest import login
from test_engineering import enter_panel
from test_org_admin import owner_password

STRONG = "correct-horse-battery"


def test_an_organisation_can_be_renamed(client, seeded):
    enter_panel(client)
    result = client.post("/admin/organisations/BA11/name", json={"name": "Bank Alpha"})
    assert result.status_code == 200, result.text
    assert result.json()["name"] == "Bank Alpha"

    listed = {org["code"]: org for org in
              client.get("/admin/organisations").json()["organisations"]}
    assert listed["BA11"]["name"] == "Bank Alpha"


def test_renaming_never_moves_the_code(client, seeded):
    """The code is the identifier people sign in with and the one written into audit
    rows. Renaming must leave it alone, or the history detaches from the organisation
    that made it and everyone is locked out."""
    enter_panel(client)
    client.post("/admin/organisations/BA11/name", json={"name": "Bank Alpha"})
    client.cookies.clear()
    assert login(client, "BA11", "clerk1").status_code == 200


def test_a_rename_cannot_collide_with_another_organisation(client, seeded):
    enter_panel(client)
    existing = client.get("/admin/organisations").json()["organisations"]
    other = next(org["name"] for org in existing if org["code"] == "BB22")
    assert client.post("/admin/organisations/BA11/name",
                       json={"name": other}).status_code == 409


def test_a_clerk_can_be_promoted_to_org_admin(client, seeded):
    enter_panel(client)
    clerk = next(u for u in client.get("/admin/users").json()["users"]
                 if u["username"] == "clerk1")

    result = client.post(f"/admin/users/{clerk['user_id']}/role", json={"role": "org_admin"})
    assert result.status_code == 200, result.text
    assert result.json() == {"user_id": clerk["user_id"], "username": "clerk1",
                             "role": "org_admin", "previous_role": "clerk",
                             "org_code": "BA11"}

    client.cookies.clear()
    login(client, "BA11", "clerk1")
    assert client.get("/org/users").status_code == 200  # the new role actually carries


def test_a_role_must_suit_the_organisation_type(client, seeded):
    """A shop does not enrol, so nobody at a shop is a clerk."""
    enter_panel(client)
    rep = next(u for u in client.get("/admin/users").json()["users"]
               if u["username"] == "rep1")
    r = client.post(f"/admin/users/{rep['user_id']}/role", json={"role": "clerk"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_an_engineer_cannot_be_moved_to_any_other_role(client, seeded):
    """Not by a last-engineer rule - by the organisation's type.

    Engineer is the only role valid in an operator organisation, so every other role is
    refused before any headcount is considered. Worth pinning, because the obvious guard
    to write here is a last-engineer check, and it would be a branch that never runs.
    """
    enter_panel(client)
    engineer = next(u for u in client.get("/admin/users").json()["users"]
                    if u["role"] == "engineer")
    for role in ("clerk", "verifier", "org_admin"):
        r = client.post(f"/admin/users/{engineer['user_id']}/role", json={"role": role})
        assert r.status_code == 422, role
        assert r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"

    # The account is untouched and the panel still answers to it.
    assert client.get("/admin/users").status_code == 200


def test_nobody_can_change_their_own_role(client, seeded):
    enter_panel(client)
    me = client.get("/auth/me").json()
    r = client.post(f"/admin/users/{me['user_id']}/role", json={"role": "verifier"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("CANNOT_CHANGE_OWN_ROLE", "ROLE_NOT_ALLOWED")


# --- what an organisation administrator may change ---------------------------


def make_admin(client, org_code: str, username: str) -> None:
    from test_org_admin import make_admin as build
    build(client, org_code, username)


def test_an_org_admin_promotes_inside_its_own_organisation(client, seeded):
    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))

    clerk = next(u for u in client.get("/org/users").json()["users"]
                 if u["username"] == "clerk1")
    r = client.post(f"/org/users/{clerk['user_id']}/role", json={"role": "verifier"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "verifier"


def test_an_org_admin_cannot_grant_the_engineer_role(client, seeded):
    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))

    clerk = next(u for u in client.get("/org/users").json()["users"]
                 if u["username"] == "clerk1")
    r = client.post(f"/org/users/{clerk['user_id']}/role", json={"role": "engineer"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_an_org_admin_cannot_change_a_role_in_another_organisation(client, seeded):
    enter_panel(client)
    victim = next(u for u in client.get("/admin/users").json()["users"]
                  if u["username"] == "clerk2")  # Bank B
    client.cookies.clear()

    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))

    # Not found, not forbidden: a scoped administrator must not learn the id exists.
    assert client.post(f"/org/users/{victim['user_id']}/role",
                       json={"role": "verifier"}).status_code == 404


# --- finding an account among many -------------------------------------------


def test_the_account_list_is_paged_and_reports_a_total(client, seeded):
    """Without a total the caller cannot tell a full page from the end of the data."""
    enter_panel(client)
    for index in range(12):
        client.post("/admin/users", json={"org_code": "BA11", "username": f"temp{index}",
                                          "role": "clerk"})

    first = client.get("/admin/users?limit=5").json()
    assert len(first["users"]) == 5
    assert first["total"] >= 13
    assert first["offset"] == 0

    second = client.get("/admin/users?limit=5&offset=5").json()
    assert len(second["users"]) == 5
    assert second["total"] == first["total"]
    overlap = {u["user_id"] for u in first["users"]} & {u["user_id"] for u in second["users"]}
    assert overlap == set(), "pages must not repeat an account"


def test_accounts_can_be_searched(client, seeded):
    enter_panel(client)
    client.post("/admin/users", json={"org_code": "BA11", "username": "findme",
                                      "role": "clerk"})

    by_name = client.get("/admin/users?q=findme").json()
    assert [u["username"] for u in by_name["users"]] == ["findme"]
    assert by_name["total"] == 1

    by_org = client.get("/admin/users?q=BB22").json()
    assert by_org["users"] and all(u["org_code"] == "BB22" for u in by_org["users"])

    by_role = client.get("/admin/users?role=engineer").json()
    assert by_role["users"] and all(u["role"] == "engineer" for u in by_role["users"])

    assert client.get("/admin/users?q=nothing-matches-this").json()["total"] == 0


def test_an_org_admin_search_cannot_reach_another_organisation(client, seeded):
    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))

    # A search naming the other organisation still returns only this one's accounts.
    body = client.get("/org/users?q=BB22").json()
    assert body["users"] == []
    assert body["total"] == 0


def test_a_row_says_why_it_cannot_be_deleted(client, seeded):
    """"Has history" is true of everything and useful for nothing. The panel should not
    offer a button that always fails, and when it withholds one it should say what is in
    the way - the server already knows, so there is nothing to guess at."""
    from test_enrolment import do_full_enrolment
    from test_signature_core import make_signature
    from test_verify import png, verify

    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456790")
    verify(client, "123456790", png(make_signature()))
    client.cookies.clear()

    enter_panel(client)
    clerk = next(u for u in client.get("/admin/users").json()["users"]
                 if u["username"] == "clerk1")
    assert clerk["deletable"] is False
    assert any("verification" in reason for reason in clerk["blockers"])

    orgs = {o["code"]: o for o in client.get("/admin/organisations").json()["organisations"]}
    bank = orgs["BA11"]
    assert bank["deletable"] is False
    assert any("customer" in reason for reason in bank["blockers"])

    # And the reasons are real: the delete genuinely refuses, naming the same things.
    refused = client.delete("/admin/organisations/BA11")
    assert refused.status_code == 409
    for reason in bank["blockers"]:
        assert reason in refused.json()["error"]["message"]


def test_an_empty_organisation_reports_itself_deletable(client, seeded):
    enter_panel(client)
    client.post("/admin/organisations", json={"code": "NEW1", "name": "Fresh Bank",
                                              "type": "financial"})
    orgs = {o["code"]: o for o in client.get("/admin/organisations").json()["organisations"]}
    assert orgs["NEW1"]["deletable"] is True
    assert orgs["NEW1"]["blockers"] == []
    assert client.delete("/admin/organisations/NEW1").status_code == 200


def test_the_operator_never_offers_deletion(client, seeded):
    """It runs the registry. Not deletable whatever it holds, and the panel says so
    rather than showing a button that would be refused."""
    enter_panel(client)
    orgs = {o["code"]: o for o in client.get("/admin/organisations").json()["organisations"]}
    operator = next(o for o in orgs.values() if o["type"] == "operator")
    assert operator["deletable"] is False
    assert operator["blockers"] == ["the operator organisation runs the registry"]
