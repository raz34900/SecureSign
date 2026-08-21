from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify

# Exact, not a subset: the list view is the widest-read endpoint in the product, so a
# field appearing here that nobody chose is how a leak arrives. `has_image` is a boolean,
# never the image itself - the picture is only served by the detail endpoint, one row at
# a time, and each read is audited.
FIELDS = {"request_id", "verdict", "distance", "threshold_used", "confidence",
          "model_version", "created_at", "customer_name", "national_id_masked",
          "performed_by", "feedback", "has_image"}


def seed_two_orgs(client):
    """Bank A enrols and verifies; Shop B verifies the same customer. Leaves Shop B logged in."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456785")
    verify(client, "123456785", png(make_signature()))
    client.cookies.clear()
    login(client, "SB44", "rep1")
    verify(client, "123456785", png(make_signature(seed=9)))


def seed_as_the_bank(client, national_id: str = "123456785"):
    """Bank A enrols and verifies, and stays signed in. Reporting is the bank's to do."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, national_id)
    verify(client, national_id, png(make_signature()))


def test_history_scoped_to_own_org(client, seeded):
    seed_two_orgs(client)
    r = client.get("/verifications")
    assert r.status_code == 200
    items = r.json()["verifications"]
    assert len(items) == 1  # only Shop B's own - Bank A's is invisible
    assert set(items[0].keys()) == FIELDS


def test_history_row_identifies_the_customer_and_operator(client, seeded):
    """A row nobody can act on is not history. It has to name who was checked, by whom."""
    seed_two_orgs(client)
    row = client.get("/verifications").json()["verifications"][0]
    assert row["customer_name"] == "Test Person"
    assert row["performed_by"] == "rep1"
    assert row["feedback"] is None


def test_history_never_returns_the_full_national_id(client, seeded):
    seed_two_orgs(client)
    row = client.get("/verifications").json()["verifications"][0]
    assert row["national_id_masked"] == "•••••6785"
    assert "123456785" not in str(row)


def test_history_filters_by_verdict_and_national_id(client, seeded):
    seed_two_orgs(client)
    verdict = client.get("/verifications").json()["verifications"][0]["verdict"]
    other = "FRAUD" if verdict == "VALID" else "VALID"

    assert len(client.get(f"/verifications?verdict={verdict}").json()["verifications"]) == 1
    assert client.get(f"/verifications?verdict={other}").json()["verifications"] == []
    assert len(client.get("/verifications?national_id=123456785").json()["verifications"]) == 1
    assert client.get("/verifications?national_id=999999999").json()["verifications"] == []


def test_history_rejects_a_malformed_national_id_filter(client, seeded):
    seed_two_orgs(client)
    assert client.get("/verifications?national_id=abc").status_code == 422


def test_reporting_a_wrong_result_queues_it_for_engineering(client, seeded, session_factory):
    seed_as_the_bank(client)
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]

    r = client.post(f"/verifications/{request_id}/feedback",
                    json={"claimed_label": "genuine", "comment": "Customer confirmed in branch."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    row = client.get("/verifications").json()["verifications"][0]
    assert row["feedback"] == {"claimed_label": "genuine", "status": "pending"}

    from backend.app.models_db import AuditLog, ModelFeedback
    with session_factory() as db:
        stored = db.query(ModelFeedback).one()
        assert stored.source == "institution" and stored.verification_id == request_id
        assert db.query(AuditLog).filter_by(action="report_verification").count() == 1


def test_reporting_never_changes_the_stored_verdict(client, seeded, session_factory):
    """An institution cannot rewrite its own history, only flag it."""
    seed_as_the_bank(client)
    row = client.get("/verifications").json()["verifications"][0]
    client.post(f"/verifications/{row['request_id']}/feedback", json={"claimed_label": "forged"})

    from backend.app.models_db import Verification
    with session_factory() as db:
        assert db.get(Verification, row["request_id"]).decision == row["verdict"]


def test_a_result_can_only_be_reported_once(client, seeded):
    seed_as_the_bank(client)
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    body = {"claimed_label": "forged"}
    assert client.post(f"/verifications/{request_id}/feedback", json=body).status_code == 200
    r = client.post(f"/verifications/{request_id}/feedback", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_REPORTED"


def test_cannot_report_another_orgs_verification(client, seeded):
    """Bank B may report, being an institution, but not Bank A's verification."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456786")
    verify(client, "123456786", png(make_signature()))
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    r = client.post(f"/verifications/{request_id}/feedback", json={"claimed_label": "forged"})
    assert r.status_code == 404


def test_reporting_rejects_an_unknown_label(client, seeded):
    seed_as_the_bank(client)
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    r = client.post(f"/verifications/{request_id}/feedback", json={"claimed_label": "maybe"})
    assert r.status_code == 422


def test_history_requires_auth(client, seeded):
    assert client.get("/verifications").status_code == 401


def test_a_subscriber_cannot_report_a_result(client, seeded):
    """The incentive is the reason, not a general mistrust of shops.

    A merchant is paid whether or not the signature was genuine, and a FRAUD verdict is
    the thing standing between them and the sale - so the cheapest correction they can
    file is always "that fraud was fine". These reports are the engineering team's ground
    truth for judging the model, which makes the one party with a standing reason to
    misreport the one party that must not be able to.
    """
    seed_two_orgs(client)  # leaves the shop signed in, looking at its own verification
    row = client.get("/verifications").json()["verifications"][0]

    refused = client.post(f"/verifications/{row['request_id']}/feedback",
                          json={"claimed_label": "genuine"})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"

    from backend.app.models_db import ModelFeedback
    assert row["feedback"] is None


def test_a_subscriber_can_still_read_its_own_history(client, seeded):
    """Reading is not the problem; filing a claim about the model is. A shop must still
    be able to look back at what it checked."""
    seed_two_orgs(client)
    rows = client.get("/verifications").json()["verifications"]
    assert len(rows) == 1
    assert client.get(f"/verifications/{rows[0]['request_id']}").status_code == 200


def test_an_org_admin_at_a_shop_cannot_report_either(client, seeded):
    """The senior account at a subscriber is still a subscriber. Gating on the clerk role
    gets this right by construction: IMPLIED_ROLES grants clerk at a financial
    organisation and never at a subscriber."""
    from test_org_admin import make_admin, owner_password

    seed_two_orgs(client)
    row = client.get("/verifications").json()["verifications"][0]
    client.cookies.clear()

    make_admin(client, "SB44", "boss2")
    client.cookies.clear()
    login(client, "SB44", "boss2", password=owner_password("boss2"))
    assert client.post(f"/verifications/{row['request_id']}/feedback",
                       json={"claimed_label": "genuine"}).status_code in (403, 404)


def test_only_the_enrolling_role_may_report(client, seeded):
    """Narrower than "any institution": the clerk role, plus an org_admin at a financial
    organisation, which is what IMPLIED_ROLES expands. A plain verifier cannot report
    even at a bank - they hold no reference set and did not enrol anyone, so a claim
    about the model is not theirs to file. If that proves too tight in practice the fix
    is to widen this gate deliberately, not to discover it by accident.
    """
    from test_engineering import enter_panel

    enter_panel(client)
    created = client.post("/admin/users", json={
        "org_code": "BA11", "username": "bankver", "role": "verifier"}).json()
    client.cookies.clear()

    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456787")
    verify(client, "123456787", png(make_signature()))
    row = client.get("/verifications").json()["verifications"][0]
    client.cookies.clear()

    login(client, "BA11", "bankver", password=created["initial_password"])
    client.post("/auth/password", json={"current_password": created["initial_password"],
                                        "new_password": "Bank-Verifier-1!"})
    assert client.post(f"/verifications/{row['request_id']}/feedback",
                       json={"claimed_label": "genuine"}).status_code == 403


def test_a_financial_org_admin_may_report(client, seeded):
    """The senior account at a bank is a clerk by implication, so it can."""
    from test_org_admin import make_admin, owner_password

    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456788")
    verify(client, "123456788", png(make_signature()))
    row = client.get("/verifications").json()["verifications"][0]
    client.cookies.clear()

    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))
    assert client.post(f"/verifications/{row['request_id']}/feedback",
                       json={"claimed_label": "genuine"}).status_code == 200
