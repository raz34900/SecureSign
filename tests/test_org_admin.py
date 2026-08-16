"""An org_admin runs its own organisation, and only its own.

Two things are being pinned here. An org_admin has the senior account for its kind of
organisation, so it can do the work as well as manage the people. And every account
operation is scoped to the caller's own organisation from the session, so Bank A has no
reachable path to Bank B's users.
"""
import pytest

from conftest import login
from test_enrolment import do_full_enrolment, enrol_body

STRONG = "correct-horse-battery"


def make_admin(client, org_code: str, username: str) -> str:
    """Create an org_admin through the provider panel and clear its first-login flag."""
    from test_engineering import enter_panel

    client.cookies.clear()
    enter_panel(client)
    created = client.post("/admin/users", json={
        "org_code": org_code, "username": username, "role": "org_admin",
        "password": STRONG}).json()

    client.cookies.clear()
    client.headers.pop("X-Internal-Panel", None)
    login(client, org_code, username, password=STRONG)
    client.post("/auth/password", json={"current_password": STRONG,
                                        "new_password": f"{STRONG}-{username}"})
    return created["user_id"]


@pytest.fixture
def bank_admin(client, seeded):
    """Signed in as an org_admin at Bank A (financial)."""
    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=f"{STRONG}-boss1")
    return client


# --- senior permissions for the organisation's own work ---------------------


def test_a_financial_org_admin_can_do_a_clerks_work(bank_admin):
    """"Highest permissions for the type of organisation": at a bank that means enrolling."""
    customer_id = do_full_enrolment(bank_admin, "123456800")
    assert bank_admin.get(f"/customers/{customer_id}").status_code == 200
    assert bank_admin.get("/customers/lookup/123456800").status_code == 200


def test_a_subscriber_org_admin_verifies_but_cannot_enrol(client, seeded):
    make_admin(client, "SB44", "boss2")
    client.cookies.clear()
    login(client, "SB44", "boss2", password=f"{STRONG}-boss2")

    # A shop does not enrol, so its administrator does not either.
    assert client.post("/customers", json=enrol_body("123456801")).status_code == 403
    # Verifying is the shop's job, and reaching the endpoint at all proves the role carries.
    assert client.post("/verify", data={"national_id": "123456801"},
                       files={"file": ("s.png", b"not-an-image", "image/png")}).status_code != 403


def test_an_org_admin_never_reaches_the_engineering_panel(bank_admin):
    bank_admin.headers.update({"X-Internal-Panel": "1"})
    assert bank_admin.get("/engineering/overview").status_code == 403
    assert bank_admin.get("/admin/users").status_code == 403


# --- managing its own organisation ------------------------------------------


def test_an_org_admin_sees_only_its_own_organisations_users(bank_admin):
    body = bank_admin.get("/org/users").json()
    assert body["organisation"] == {"code": "BA11", "name": "Bank A", "type": "financial"}
    assert {row["username"] for row in body["users"]} == {"clerk1", "boss1"}


def test_an_org_admin_creates_a_colleague_who_must_pick_a_password(client, bank_admin):
    r = bank_admin.post("/org/users", json={"username": "clerk5", "role": "clerk",
                                            "password": STRONG})
    assert r.status_code == 200, r.text
    assert r.json()["org_code"] == "BA11"
    assert r.json()["must_change_password"] is True

    client.cookies.clear()
    assert login(client, "BA11", "clerk5", password=STRONG).status_code == 200
    # Nothing works until the handed-out password is replaced.
    blocked = client.get("/customers/lookup/123456789")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    client.post("/auth/password", json={"current_password": STRONG,
                                        "new_password": "a-different-long-one"})
    assert client.get("/customers/lookup/123456789").status_code == 404  # reached the handler


def test_an_org_admin_cannot_mint_an_engineer(bank_admin):
    r = bank_admin.post("/org/users", json={"username": "sneaky", "role": "engineer",
                                            "password": STRONG})
    assert r.status_code == 422


def test_an_org_admin_resets_a_colleagues_password_and_cuts_their_session(other_client,
                                                                          bank_admin):
    clerk_id = next(row["user_id"] for row in bank_admin.get("/org/users").json()["users"]
                    if row["username"] == "clerk1")

    assert login(other_client, "BA11", "clerk1").status_code == 200      # signed in elsewhere
    result = bank_admin.post(f"/org/users/{clerk_id}/password",
                             json={"password": "brand-new-password"})
    assert result.json()["sessions_revoked"] == 1
    assert other_client.get("/auth/me").status_code == 401

    assert login(other_client, "BA11", "clerk1").status_code == 401      # old password dead
    assert login(other_client, "BA11", "clerk1",
                 password="brand-new-password").status_code == 200


def test_an_org_admin_deletes_a_colleague_with_no_history(client, bank_admin):
    bank_admin.post("/org/users", json={"username": "clerk6", "role": "clerk",
                                        "password": STRONG})
    user_id = next(row["user_id"] for row in bank_admin.get("/org/users").json()["users"]
                   if row["username"] == "clerk6")

    assert bank_admin.delete(f"/org/users/{user_id}").status_code == 200
    assert "clerk6" not in {row["username"] for row in
                            bank_admin.get("/org/users").json()["users"]}
    client.cookies.clear()
    assert login(client, "BA11", "clerk6", password=STRONG).status_code == 401


def test_an_org_admin_cannot_delete_itself(bank_admin):
    own_id = next(row["user_id"] for row in bank_admin.get("/org/users").json()["users"]
                  if row["username"] == "boss1")
    r = bank_admin.delete(f"/org/users/{own_id}")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CANNOT_DELETE_SELF"


# --- cross-organisation isolation -------------------------------------------


def test_bank_a_cannot_touch_bank_b_users(client, seeded):
    """The check asked for directly: A must not read, disable, reset or delete B."""
    from test_engineering import enter_panel

    enter_panel(client)
    victim = next(row["user_id"] for row in client.get("/admin/users").json()["users"]
                  if row["username"] == "clerk2")  # Bank B
    client.cookies.clear()
    client.headers.pop("X-Internal-Panel", None)

    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=f"{STRONG}-boss1")

    listed = {row["username"] for row in client.get("/org/users").json()["users"]}
    assert "clerk2" not in listed

    # Not forbidden - not found. A scoped administrator must not learn that the id exists.
    assert client.post(f"/org/users/{victim}/active", json={"is_active": False}).status_code == 404
    assert client.post(f"/org/users/{victim}/password",
                       json={"password": "attacker-chosen-pw"}).status_code == 404
    assert client.delete(f"/org/users/{victim}").status_code == 404

    # And the victim is untouched.
    client.cookies.clear()
    assert login(client, "BB22", "clerk2").status_code == 200


def test_org_admin_endpoints_reject_every_other_role(client, seeded):
    for org, username in (("BA11", "clerk1"), ("SB44", "rep1")):
        client.cookies.clear()
        login(client, org, username)
        assert client.get("/org/users").status_code == 403
        assert client.post("/org/users", json={"username": "x1", "role": "clerk",
                                               "password": STRONG}).status_code == 403


def test_org_admin_endpoints_require_auth(client, seeded):
    assert client.get("/org/users").status_code == 401
