"""Engineering panel: internal-only, aggregate model monitoring with no route to customer data."""
import json

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify

CUSTOMER_NAME = "Test Person"
NATIONAL_ID = "123456790"

def enter_panel(client, org_code="SS00", username="eng1"):
    """Sign in to the panel.

    Reaching it is a deployment control, not an application one: the public entrypoint
    404s this prefix and the internal listener is published on the host loopback only.
    The application itself does not distinguish callers, so nothing is stamped here.
    """
    login(client, org_code, username)


def seed_activity(client):
    """One enrolment, one verification, one institution report. Leaves nobody logged in."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, NATIONAL_ID)
    verify(client, NATIONAL_ID, png(make_signature()))
    request_id = client.get("/verifications").json()["verifications"][0]["request_id"]
    client.post(f"/verifications/{request_id}/feedback",
                json={"claimed_label": "forged", "comment": "Branch disputed the result."})
    client.cookies.clear()


def test_overview_reports_registry_and_model_state(client, seeded):
    seed_activity(client)
    enter_panel(client)

    body = client.get("/engineering/overview").json()
    assert body["registry"] == {"customers": 1, "reference_signatures": 9, "organisations": 5}
    assert body["verifications"]["total"] == 1
    assert body["model"]["threshold"] == 0.3999
    assert body["model"]["version"]
    assert body["feedback"] == {"pending": 1}

    buckets = body["distance_histogram"]
    assert len(buckets) == 20
    assert sum(bucket["count"] for bucket in buckets) == 1
    assert buckets[0]["lower"] == 0.0 and buckets[-1]["upper"] == 1.0


def test_overview_exposes_no_customer_data(client, seeded):
    """Book 10.1.6: the engineering role monitors the model, never the customers."""
    seed_activity(client)
    enter_panel(client)

    body = json.dumps(client.get("/engineering/overview").json())
    assert CUSTOMER_NAME not in body
    assert NATIONAL_ID not in body
    assert "image" not in body and "base64" not in body


def test_feedback_queue_carries_the_score_but_not_the_customer(client, seeded):
    seed_activity(client)
    enter_panel(client)

    items = client.get("/engineering/feedback").json()["feedback"]
    assert len(items) == 1
    report = items[0]
    assert report["status"] == "pending"
    assert report["source"] == "institution"
    assert report["claimed_label"] == "forged"
    assert report["verification"]["verdict"] in {"VALID", "FRAUD"}
    assert 0.0 <= report["verification"]["distance"]
    assert report["verification"]["band"] in ("valid", "fraud", "borderline")

    body = json.dumps(report)
    assert CUSTOMER_NAME not in body and NATIONAL_ID not in body


def test_feedback_names_the_reporting_institution_and_its_record(client, seeded):
    """An engineer who cannot see the signature can still weigh who is disputing it."""
    seed_activity(client)
    enter_panel(client)

    reporter = client.get("/engineering/feedback").json()["feedback"][0]["reporter"]
    assert reporter["organisation"] == "Bank A"
    assert reporter["type"] == "financial"
    assert reporter["reports"] == {"total": 1, "accepted": 0, "rejected": 0, "pending": 1}


def test_a_reporters_record_accumulates_across_reports(client, seeded):
    """The anti-poisoning signal: an institution whose reports keep being rejected."""
    login(client, "BA11", "clerk1")
    for national_id in ("123456791", "123456792"):
        do_full_enrolment(client, national_id)
        verify(client, national_id, png(make_signature()))
    for row in client.get("/verifications").json()["verifications"]:
        client.post(f"/verifications/{row['request_id']}/feedback",
                    json={"claimed_label": "forged"})
    client.cookies.clear()

    enter_panel(client)
    pending = client.get("/engineering/feedback").json()["feedback"]
    assert len(pending) == 2
    client.post(f"/engineering/feedback/{pending[0]['feedback_id']}",
                json={"status": "rejected"})

    remaining = client.get("/engineering/feedback?status=pending").json()["feedback"][0]
    assert remaining["reporter"]["reports"] == {
        "total": 2, "accepted": 0, "rejected": 1, "pending": 1}


def test_feedback_queue_filters_by_status(client, seeded):
    seed_activity(client)
    enter_panel(client)
    assert len(client.get("/engineering/feedback?status=pending").json()["feedback"]) == 1
    assert client.get("/engineering/feedback?status=accepted").json()["feedback"] == []


def test_engineer_accepts_a_report(client, seeded, session_factory):
    seed_activity(client)
    enter_panel(client)
    feedback_id = client.get("/engineering/feedback").json()["feedback"][0]["feedback_id"]

    r = client.post(f"/engineering/feedback/{feedback_id}", json={"status": "accepted"})
    assert r.status_code == 200, r.text
    assert client.get("/engineering/feedback?status=accepted").json()["feedback"][0][
        "feedback_id"] == feedback_id

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(
            action="review_feedback", resource_id=feedback_id).count() == 1


def test_a_report_cannot_be_reviewed_twice(client, seeded):
    seed_activity(client)
    enter_panel(client)
    feedback_id = client.get("/engineering/feedback").json()["feedback"][0]["feedback_id"]

    assert client.post(f"/engineering/feedback/{feedback_id}",
                       json={"status": "rejected"}).status_code == 200
    r = client.post(f"/engineering/feedback/{feedback_id}", json={"status": "accepted"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_REVIEWED"


def test_unknown_report_is_not_found(client, seeded):
    enter_panel(client)
    r = client.post("/engineering/feedback/does-not-exist", json={"status": "accepted"})
    assert r.status_code == 404


def test_panel_is_engineer_only(client, seeded):
    for org, username in (("BA11", "clerk1"), ("SB44", "rep1")):
        client.cookies.clear()
        enter_panel(client, org, username)
        assert client.get("/engineering/overview").status_code == 403
        assert client.get("/engineering/feedback").status_code == 403


def test_panel_requires_auth(client, seeded):
    assert client.get("/engineering/overview").status_code == 401


# --- reachability is a deployment control -----------------------------------


def test_the_application_does_not_gate_the_panel_by_caller(client, seeded):
    """Deliberate: the app authorises by role, and reachability is nginx plus the port
    binding. Asserted so nobody reintroduces a caller check that a header could forge."""
    import inspect

    from backend.app.auth import deps
    from backend.app.routers import accounts, engineering

    assert not hasattr(deps, "require_internal")
    for module in (engineering, accounts):
        assert "X-Internal-Panel" not in inspect.getsource(module)
    login(client, "SS00", "eng1")
    assert client.get("/engineering/overview").status_code == 200


def test_engineer_cannot_reach_customer_or_verification_data(client, seeded):
    """The panel is the engineer's only door; every customer route stays shut."""
    seed_activity(client)
    enter_panel(client)
    assert client.get(f"/customers/lookup/{NATIONAL_ID}").status_code == 403
    assert client.get("/verifications").status_code == 403
