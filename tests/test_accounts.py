"""Account provisioning: internal-only, and the rules that stop it creating a way in.

The gate is network location, not job title - creating accounts is the highest-privilege
operation in the system, so it lives behind the same internal-only door as the
engineering panel and is never reachable from the public web.
"""
import pytest

from conftest import login
from test_engineering import enter_panel
from test_enrolment import do_full_enrolment

NEW_BANK = {"code": "NB77", "name": "New Bank", "type": "financial"}


def new_user(**overrides) -> dict:
    body = {"org_code": "NB77", "username": "clerk9", "role": "clerk",
            "password": "correct-horse-battery"}
    return {**body, **overrides}


@pytest.fixture
def admin(client, seeded):
    """An engineer arriving through the internal entrypoint."""
    enter_panel(client)
    return client


# --- organisations ---------------------------------------------------------


def test_creating_an_organisation_makes_it_listable(admin):
    r = admin.post("/admin/organisations", json=NEW_BANK)
    assert r.status_code == 200, r.text
    assert r.json() == {"code": "NB77", "name": "New Bank", "type": "financial",
                        "is_active": True}

    listed = admin.get("/admin/organisations").json()["organisations"]
    assert {org["code"] for org in listed} == {"SS00", "BA11", "BB22", "SA33", "SB44", "NB77"}
    created = next(org for org in listed if org["code"] == "NB77")
    assert created["active_users"] == 0


def test_duplicate_organisation_code_is_rejected(admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    r = admin.post("/admin/organisations", json={**NEW_BANK, "name": "Different Name"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_ORGANISATION"


@pytest.mark.parametrize("code", ["nb77", "NB 77", "N", "NB-77", ""])
def test_organisation_codes_are_validated(admin, code):
    assert admin.post("/admin/organisations", json={**NEW_BANK, "code": code}).status_code == 422


def test_an_unknown_organisation_type_is_rejected(admin):
    r = admin.post("/admin/organisations", json={**NEW_BANK, "type": "government"})
    assert r.status_code == 422


# --- users -----------------------------------------------------------------


def test_a_created_user_can_sign_in(client, admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    r = admin.post("/admin/users", json=new_user())
    assert r.status_code == 200, r.text
    assert "password" not in r.json() and "password_hash" not in r.json()

    client.cookies.clear()
    signed_in = login(client, "NB77", "clerk9", password="correct-horse-battery")
    assert signed_in.status_code == 200
    assert signed_in.json() == {"role": "clerk", "org_type": "financial",
                                "must_change_password": True}


def test_a_role_must_suit_the_organisation(admin):
    """The engineer rule is the one that matters: an institution must not be able to
    hold an account that reaches the engineering panel."""
    admin.post("/admin/organisations", json=NEW_BANK)
    r = admin.post("/admin/users", json=new_user(username="sneaky", role="engineer"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"

    # A clerk belongs to a financial institution, not a shop.
    assert admin.post("/admin/users", json=new_user(
        org_code="SB44", username="clerk8")).status_code == 422


def test_an_engineer_can_be_created_in_the_operator(admin):
    r = admin.post("/admin/users", json=new_user(
        org_code="SS00", username="eng2", role="engineer"))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "engineer"


def test_a_short_password_is_rejected(admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    r = admin.post("/admin/users", json=new_user(password="short"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"


def test_a_duplicate_username_within_an_organisation_is_rejected(admin):
    r = admin.post("/admin/users", json=new_user(org_code="BA11", username="clerk1"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_USER"


def test_the_same_username_may_exist_in_two_organisations(admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    assert admin.post("/admin/users", json=new_user(
        org_code="NB77", username="clerk1")).status_code == 200


def test_a_user_cannot_be_created_in_an_unknown_organisation(admin):
    r = admin.post("/admin/users", json=new_user(org_code="ZZ99"))
    assert r.status_code == 404


def test_listing_users_never_returns_password_material(admin):
    body = admin.get("/admin/users").json()
    assert len(body["users"]) == 5
    # must_change_password is a flag, not a secret; a hash or a plaintext is neither.
    assert all(set(row) & {"password", "password_hash"} == set() for row in body["users"])
    assert "argon2" not in str(body)
    assert {row["org_code"] for row in body["users"]} == {"SS00", "BA11", "BB22", "SA33", "SB44"}


# --- deactivation ----------------------------------------------------------


def test_deactivating_a_user_stops_them_signing_in(client, admin):
    user_id = next(row["user_id"] for row in admin.get("/admin/users").json()["users"]
                   if row["username"] == "clerk1")
    assert admin.post(f"/admin/users/{user_id}/active",
                      json={"is_active": False}).status_code == 200

    client.cookies.clear()
    assert login(client, "BA11", "clerk1").status_code == 401


def test_a_deactivated_user_can_be_restored(client, admin):
    user_id = next(row["user_id"] for row in admin.get("/admin/users").json()["users"]
                   if row["username"] == "clerk1")
    admin.post(f"/admin/users/{user_id}/active", json={"is_active": False})
    admin.post(f"/admin/users/{user_id}/active", json={"is_active": True})

    client.cookies.clear()
    assert login(client, "BA11", "clerk1").status_code == 200


def test_you_cannot_deactivate_yourself(admin):
    user_id = next(row["user_id"] for row in admin.get("/admin/users").json()["users"]
                   if row["username"] == "eng1")
    r = admin.post(f"/admin/users/{user_id}/active", json={"is_active": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CANNOT_DEACTIVATE_SELF"


def test_the_last_engineer_cannot_be_deactivated(client, admin):
    """Otherwise the panel locks itself, and the only way back is the seed script."""
    admin.post("/admin/users", json=new_user(
        org_code="SS00", username="eng2", role="engineer"))
    users = admin.get("/admin/users").json()["users"]
    eng2 = next(row["user_id"] for row in users if row["username"] == "eng2")
    eng1 = next(row["user_id"] for row in users if row["username"] == "eng1")

    # Two engineers: removing one is fine.
    assert admin.post(f"/admin/users/{eng2}/active",
                      json={"is_active": False}).status_code == 200

    # eng1 is now the only one left, and is also the caller.
    client.cookies.clear()
    login(client, "SS00", "eng2")  # deactivated: cannot get back in
    enter_panel(client)
    r = client.post(f"/admin/users/{eng1}/active", json={"is_active": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in {"LAST_ENGINEER", "CANNOT_DEACTIVATE_SELF"}


def test_deactivating_an_organisation_stops_its_users_signing_in(client, admin):
    assert admin.post("/admin/organisations/BA11/active",
                      json={"is_active": False}).status_code == 200
    client.cookies.clear()
    assert login(client, "BA11", "clerk1").status_code == 401


def test_the_operator_organisation_cannot_be_deactivated(admin):
    r = admin.post("/admin/organisations/SS00/active", json={"is_active": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in {"CANNOT_DEACTIVATE_SELF",
                                         "CANNOT_DEACTIVATE_OPERATOR"}


def test_a_deactivated_organisation_takes_no_new_users(admin):
    admin.post("/admin/organisations/BA11/active", json={"is_active": False})
    r = admin.post("/admin/users", json=new_user(org_code="BA11", username="clerk7"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ORGANISATION_INACTIVE"


# --- passwords -------------------------------------------------------------


def user_id_of(admin, username: str) -> str:
    return next(row["user_id"] for row in admin.get("/admin/users").json()["users"]
                if row["username"] == username)


def test_a_handed_out_password_blocks_everything_until_replaced(client, admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    admin.post("/admin/users", json=new_user())

    client.cookies.clear()
    assert login(client, "NB77", "clerk9", password="correct-horse-battery").json()[
        "must_change_password"] is True

    blocked = client.get("/customers/lookup/123456789")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    r = client.post("/auth/password", json={"current_password": "correct-horse-battery",
                                            "new_password": "something-else-entirely"})
    assert r.status_code == 200, r.text
    assert client.get("/auth/me").json()["must_change_password"] is False
    assert client.get("/customers/lookup/123456789").status_code == 404  # handler reached


def test_changing_a_password_needs_the_current_one(client, seeded):
    login(client, "BA11", "clerk1")
    r = client.post("/auth/password", json={"current_password": "not-it",
                                            "new_password": "a-long-enough-password"})
    assert r.status_code == 401


def test_a_new_password_must_be_long_and_different(client, seeded):
    login(client, "BA11", "clerk1")
    short = client.post("/auth/password", json={"current_password": "pw123456",
                                                "new_password": "tiny"})
    assert short.json()["error"]["code"] == "WEAK_PASSWORD"

    same = client.post("/auth/password", json={"current_password": "pw123456",
                                               "new_password": "pw123456"})
    assert same.json()["error"]["code"] in {"WEAK_PASSWORD", "PASSWORD_UNCHANGED"}


def test_resetting_a_password_signs_the_account_out_everywhere(other_client, admin):
    """An administrator resetting a compromised account must end its live sessions."""
    assert login(other_client, "BA11", "clerk1").status_code == 200
    assert other_client.get("/auth/me").status_code == 200

    result = admin.post(f"/admin/users/{user_id_of(admin, 'clerk1')}/password",
                        json={"password": "an-entirely-new-password"})
    assert result.status_code == 200, result.text
    assert result.json()["sessions_revoked"] == 1
    assert other_client.get("/auth/me").status_code == 401
    assert login(other_client, "BA11", "clerk1",
                 password="an-entirely-new-password").status_code == 200


def test_a_reset_password_must_be_strong(admin):
    r = admin.post(f"/admin/users/{user_id_of(admin, 'clerk1')}/password",
                   json={"password": "short"})
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"


# --- deletion ---------------------------------------------------------------


def test_a_user_with_no_history_is_deleted_outright(client, admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    admin.post("/admin/users", json=new_user())
    assert admin.delete(f"/admin/users/{user_id_of(admin, 'clerk9')}").status_code == 200
    assert "clerk9" not in {row["username"] for row in
                            admin.get("/admin/users").json()["users"]}


def test_a_user_who_has_verified_cannot_be_deleted(client, admin):
    """Deleting them would erase who checked a signature, which is the audit trail."""
    from test_signature_core import make_signature
    from test_verify import png, verify

    client.cookies.clear()
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456810")
    verify(client, "123456810", png(make_signature()))

    enter_panel(client)
    r = client.delete(f"/admin/users/{user_id_of(client, 'clerk1')}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "USER_HAS_HISTORY"
    assert "Disable it instead" in r.json()["error"]["message"]

    # Disabling remains available, and is the correct action here.
    assert client.post(f"/admin/users/{user_id_of(client, 'clerk1')}/active",
                       json={"is_active": False}).status_code == 200


def test_the_users_list_says_which_accounts_can_be_deleted(admin):
    assert all(row["deletable"] for row in admin.get("/admin/users").json()["users"])


def test_an_empty_organisation_is_deleted_outright(admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    assert admin.delete("/admin/organisations/NB77").status_code == 200
    assert "NB77" not in {org["code"] for org in
                          admin.get("/admin/organisations").json()["organisations"]}


def test_an_organisation_with_users_is_not_deleted(admin):
    r = admin.delete("/admin/organisations/BA11")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ORGANISATION_HAS_HISTORY"
    assert "user account(s)" in r.json()["error"]["message"]


def test_an_organisation_holding_customer_records_is_not_deleted(client, admin):
    admin.post("/admin/organisations", json=NEW_BANK)
    admin.post("/admin/users", json=new_user())

    client.cookies.clear()
    login(client, "NB77", "clerk9", password="correct-horse-battery")
    client.post("/auth/password", json={"current_password": "correct-horse-battery",
                                        "new_password": "something-else-entirely"})
    do_full_enrolment(client, "123456811")

    enter_panel(client)
    client.delete(f"/admin/users/{user_id_of(client, 'clerk9')}")  # blocked or not, try
    r = client.delete("/admin/organisations/NB77")
    assert r.status_code == 409
    assert "customer" in r.json()["error"]["message"] or "user" in r.json()["error"]["message"]


def test_the_operator_organisation_cannot_be_deleted(admin):
    r = admin.delete("/admin/organisations/SS00")
    assert r.status_code == 422


def test_you_cannot_delete_yourself(admin):
    r = admin.delete(f"/admin/users/{user_id_of(admin, 'eng1')}")
    assert r.status_code == 422
    assert r.json()["error"]["code"] in {"CANNOT_DELETE_SELF", "LAST_ENGINEER"}


# --- reachability ----------------------------------------------------------


def test_provisioning_is_engineer_only(client, seeded):
    for org, username in (("BA11", "clerk1"), ("SB44", "rep1")):
        client.cookies.clear()
        enter_panel(client, org, username)
        assert client.get("/admin/users").status_code == 403
        assert client.post("/admin/organisations", json=NEW_BANK).status_code == 403


def test_provisioning_requires_auth(client, seeded):
    assert client.get("/admin/organisations").status_code == 401


def test_every_change_is_audited(admin, session_factory):
    admin.post("/admin/organisations", json=NEW_BANK)
    admin.post("/admin/users", json=new_user())

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        actions = {row.action for row in db.query(AuditLog).all()}
        assert {"create_organisation", "create_user"} <= actions
