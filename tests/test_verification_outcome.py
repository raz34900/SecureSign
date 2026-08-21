"""What the counter did after reading the verdict.

The product shows a clerk which reference anchors failed and by how much, so that they
can overrule the model when they have knowledge it does not. Until this endpoint existed
that evidence was decorative: there was nowhere to say what was actually done with it.

The row lives in the audit log, not on the verification. A verdict is what the system
decided; an outcome is what a person did next, and the two must stay distinguishable.
"""
from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def run_one(client, national_id: str = "123456670") -> dict:
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, national_id)
    verify(client, national_id, png(make_signature()))
    return client.get("/verifications").json()["verifications"][0]


def record(client, request_id: str, outcome: str, reason: str | None = None):
    return client.post(f"/verifications/{request_id}/outcome",
                       json={"outcome": outcome, "reason": reason})


# The fake embedder in conftest is deterministic but not meaningful, so a fixture
# verification can land either side of the threshold. These name the relationship being
# tested rather than a verdict, so the tests say what they mean whichever way it fell.
def agreeing(row) -> str:
    return "accepted" if row["verdict"] == "VALID" else "rejected"


def contradicting(row) -> str:
    return "rejected" if row["verdict"] == "VALID" else "accepted"


def test_an_outcome_is_recorded_and_read_back_on_the_detail(client, seeded):
    row = run_one(client)
    assert client.get(f"/verifications/{row['request_id']}").json()["outcome"] is None

    written = record(client, row["request_id"], "escalated", "Sent to the branch manager.")
    assert written.status_code == 200, written.text

    body = client.get(f"/verifications/{row['request_id']}").json()
    assert body["outcome"]["outcome"] == "escalated"
    assert body["outcome"]["reason"] == "Sent to the branch manager."
    assert body["outcome"]["recorded_by"] == "clerk1"
    assert body["outcome"]["recorded_at"]


def test_agreeing_with_the_verdict_needs_no_reason(client, seeded):
    """A signature the model called genuine and the clerk honoured. Demanding an
    explanation here would train people to type "ok" and stop reading."""
    row = run_one(client, "123456671")
    assert record(client, row["request_id"], agreeing(row)).status_code == 200


def test_contradicting_the_verdict_without_a_reason_is_refused(client, seeded):
    """Refusing a signature the model passed is the clerk claiming knowledge the model
    did not have. The whole value of the row is what that knowledge was."""
    row = run_one(client, "123456672")

    refused = record(client, row["request_id"], contradicting(row))
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "REASON_REQUIRED"
    assert client.get(f"/verifications/{row['request_id']}").json()["outcome"] is None

    accepted = record(client, row["request_id"], contradicting(row),
                      "Customer could not produce identification.")
    assert accepted.status_code == 200


def test_escalating_never_counts_as_contradicting(client, seeded):
    """Sending it upstairs is declining to decide, not overruling anyone."""
    row = run_one(client, "123456673")
    assert record(client, row["request_id"], "escalated").status_code == 200


def test_an_outcome_is_recorded_once(client, seeded):
    row = run_one(client, "123456674")
    first = agreeing(row)
    assert record(client, row["request_id"], first).status_code == 200

    again = record(client, row["request_id"], "escalated", "Changed my mind.")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_RECORDED"
    assert client.get(f"/verifications/{row['request_id']}").json()["outcome"]["outcome"] \
        == first, "the first statement stands"


def test_recording_an_outcome_leaves_the_verdict_alone(client, seeded, session_factory):
    """An institution states what it did. It does not rewrite what the system decided."""
    from backend.app.models_db import Verification

    row = run_one(client, "123456675")
    record(client, row["request_id"], contradicting(row),
           "Signature looked traced in person.")

    with session_factory() as db:
        stored = db.get(Verification, row["request_id"])
        assert stored.decision == row["verdict"]
        assert stored.distance == row["distance"]


def test_another_organisation_cannot_record_an_outcome(client, seeded):
    """404, not 403: a 403 would confirm the verification exists."""
    row = run_one(client, "123456676")
    client.cookies.clear()
    login(client, "SB44", "rep1")
    assert record(client, row["request_id"], "accepted").status_code == 404


def test_a_subscriber_records_outcomes_on_its_own_checks(client, seeded):
    """Wider than /feedback on purpose. A merchant reporting "that fraud was really
    fine" is a claim about the model and is refused; a merchant recording that they
    honoured it anyway is a statement against their own interest, and is the most
    useful row in the log."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456677")
    client.cookies.clear()

    login(client, "SB44", "rep1")
    verify(client, "123456677", png(make_signature()))
    row = client.get("/verifications").json()["verifications"][0]

    assert record(client, row["request_id"], "accepted",
                  "Regular customer, known to the shop.").status_code == 200
    assert client.post(f"/verifications/{row['request_id']}/feedback",
                       json={"claimed_label": "genuine"}).status_code == 403


def test_an_unknown_verification_is_not_found(client, seeded):
    login(client, "BA11", "clerk1")
    assert record(client, "00000000-0000-0000-0000-000000000000",
                  "accepted").status_code == 404


def test_an_unauthenticated_request_is_refused(client, seeded):
    row = run_one(client, "123456678")
    client.cookies.clear()
    assert record(client, row["request_id"], "accepted").status_code == 401


def test_an_unknown_outcome_is_refused(client, seeded):
    row = run_one(client, "123456679")
    assert record(client, row["request_id"], "ignored").status_code == 422
