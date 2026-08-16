"""Engineering panel: internal-only, aggregate model monitoring with no route to customer data."""
import json

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify

CUSTOMER_NAME = "Test Person"
NATIONAL_ID = "123456790"

# The internal entrypoint stamps this; the public one strips it. See frontend/nginx.conf.
INTERNAL = {"X-Internal-Panel": "1"}


def enter_panel(client, org_code="SS00", username="eng1"):
    """Log in and arrive the way the internal entrypoint delivers a request."""
    login(client, org_code, username)
    client.headers.update(INTERNAL)


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
    assert isinstance(report["verification"]["borderline"], bool)

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
    client.headers.update(INTERNAL)
    assert client.get("/engineering/overview").status_code == 401


# --- internal-only reachability --------------------------------------------


def test_panel_is_invisible_from_the_public_entrypoint(client, seeded):
    """No marker header and no loopback caller: the panel must not even admit to existing."""
    login(client, "SS00", "eng1")
    for path in ("/engineering/overview", "/engineering/feedback"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.json()["error"]["message"] == "Not found."


def test_a_forged_marker_value_is_not_enough(client, seeded):
    login(client, "SS00", "eng1")
    client.headers.update({"X-Internal-Panel": "yes"})
    assert client.get("/engineering/overview").status_code == 404


def test_reviewing_a_report_is_internal_only_too(client, seeded):
    seed_activity(client)
    enter_panel(client)
    feedback_id = client.get("/engineering/feedback").json()["feedback"][0]["feedback_id"]

    client.headers.pop("X-Internal-Panel")
    r = client.post(f"/engineering/feedback/{feedback_id}", json={"status": "accepted"})
    assert r.status_code == 404


def test_a_caller_on_the_host_itself_needs_no_marker():
    """Running the API directly on the server is the other legitimate way in."""
    from starlette.datastructures import Address, Headers

    from backend.app.auth.deps import require_internal
    from backend.app.errors import AppError

    class Req:
        def __init__(self, host):
            self.client = Address(host, 50000) if host else None
            self.headers = Headers({})

    assert require_internal(Req("127.0.0.1")) is None
    assert require_internal(Req("::1")) is None
    for host in ("10.0.0.4", "203.0.113.7", None):
        try:
            require_internal(Req(host))
        except AppError as err:
            assert err.status == 404
        else:
            raise AssertionError(f"{host} should not reach the panel")


def test_engineer_cannot_reach_customer_or_verification_data(client, seeded):
    """The panel is the engineer's only door; every customer route stays shut."""
    seed_activity(client)
    enter_panel(client)
    assert client.get(f"/customers/lookup/{NATIONAL_ID}").status_code == 403
    assert client.get("/verifications").status_code == 403
