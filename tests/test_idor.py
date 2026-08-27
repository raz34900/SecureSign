"""IDOR + cross-org isolation: financial org vs financial org, subscriber vs subscriber.

Core asymmetry under test: verify is cross-org BY DESIGN; reads are own-org only.
A cross-org read must be indistinguishable from a nonexistent resource (no oracle).
"""
import uuid

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def test_financial_cannot_read_other_financials_customer(client, seeded):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456770")
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    r = client.get(f"/customers/{cust_id}")
    assert r.status_code == 404  # scoped read: other org's customer looks nonexistent
    assert "full_name" not in r.text and "123456770" not in r.text


def test_cross_org_read_indistinguishable_from_nonexistent(client, seeded):
    """No IDOR oracle: 404 for another org's customer == 404 for a random UUID."""
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456771")
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    foreign = client.get(f"/customers/{cust_id}")
    missing = client.get(f"/customers/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_financial_can_verify_other_financials_customer(client, seeded):
    """Positive control: cross-org VERIFY is the registry's purpose - must work."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456772")
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    r = verify(client, "123456772", png(make_signature(seed=7)))
    assert r.status_code == 200
    assert r.json()["verdict"] in ("VALID", "FRAUD")


def test_history_isolated_between_financial_orgs(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456773")
    verify(client, "123456773", png(make_signature()))
    assert len(client.get("/verifications").json()["verifications"]) == 1
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    assert client.get("/verifications").json()["verifications"] == []


def test_history_isolated_between_subscriber_orgs(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456774")
    client.cookies.clear()

    login(client, "SA33", "rep2")
    verify(client, "123456774", png(make_signature(seed=3)))
    assert len(client.get("/verifications").json()["verifications"]) == 1
    client.cookies.clear()

    login(client, "SB44", "rep1")
    assert client.get("/verifications").json()["verifications"] == []


def test_second_subscriber_rbac_matrix(client, seeded):
    """RBAC holds for every org of a type, not just the first seeded one."""
    login(client, "SA33", "rep2")
    r = client.post("/customers", json={"national_id": "123456775", "full_name": "X",
                                        "consent": {"granted": True, "method": "in_person"}})
    assert r.status_code == 403  # verifier can never enrol, regardless of org
    assert client.get(f"/customers/{uuid.uuid4()}").status_code == 403


def test_enrolment_staging_not_reachable_across_orgs(client, seeded):
    """Staged (uncommitted) enrolment ids must not be usable by another org's clerk."""
    login(client, "BA11", "clerk1")
    eid = client.post("/customers", json={"national_id": "123456776", "full_name": "Y",
                                          "consent": {"granted": True, "method": "signed_form"}}
                      ).json()["enrolment_id"]
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    from test_signature_core import make_specimen_card
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(9), "image/jpeg")})
    assert r.status_code == 404
