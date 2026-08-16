from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify

FIELDS = {"request_id", "verdict", "distance", "threshold_used", "confidence",
          "model_version", "created_at", "customer_name", "national_id_masked",
          "performed_by", "feedback"}


def seed_two_orgs(client):
    """Bank A enrols and verifies; Shop B verifies the same customer. Leaves Shop B logged in."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456785")
    verify(client, "123456785", png(make_signature()))
    client.cookies.clear()
    login(client, "SB44", "rep1")
    verify(client, "123456785", png(make_signature(seed=9)))


def test_history_scoped_to_own_org(client, seeded):
    seed_two_orgs(client)
    r = client.get("/verifications")
    assert r.status_code == 200
    items = r.json()["verifications"]
    assert len(items) == 1  # only Shop B's own — Bank A's is invisible
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
    seed_two_orgs(client)
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
    seed_two_orgs(client)
    row = client.get("/verifications").json()["verifications"][0]
    client.post(f"/verifications/{row['request_id']}/feedback", json={"claimed_label": "forged"})

    from backend.app.models_db import Verification
    with session_factory() as db:
        assert db.get(Verification, row["request_id"]).decision == row["verdict"]


def test_a_result_can_only_be_reported_once(client, seeded):
    seed_two_orgs(client)
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    body = {"claimed_label": "forged"}
    assert client.post(f"/verifications/{request_id}/feedback", json=body).status_code == 200
    r = client.post(f"/verifications/{request_id}/feedback", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_REPORTED"


def test_cannot_report_another_orgs_verification(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456786")
    verify(client, "123456786", png(make_signature()))
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    client.cookies.clear()

    login(client, "SB44", "rep1")
    r = client.post(f"/verifications/{request_id}/feedback", json={"claimed_label": "forged"})
    assert r.status_code == 404


def test_reporting_rejects_an_unknown_label(client, seeded):
    seed_two_orgs(client)
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    r = client.post(f"/verifications/{request_id}/feedback", json={"claimed_label": "maybe"})
    assert r.status_code == 422


def test_history_requires_auth(client, seeded):
    assert client.get("/verifications").status_code == 401
