import io

from PIL import Image

from conftest import login
from test_signature_core import make_specimen_card


def enrol_body(nid: str = "123456780", granted: bool = True) -> dict:
    return {"national_id": nid, "full_name": "Test Person",
            "consent": {"granted": granted, "method": "signed_form"}}


def do_full_enrolment(client, nid: str = "123456780") -> str:
    """Returns customer_id. Assumes clerk already logged in."""
    r = client.post("/customers", json=enrol_body(nid))
    assert r.status_code == 200, r.text
    eid = r.json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(6), "image/jpeg")})
    assert r.status_code == 200, r.text
    crop_ids = [c["crop_id"] for c in r.json()["crops"]][:6]
    r = client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})
    assert r.status_code == 200, r.text
    return r.json()["customer_id"]


def test_enrolment_requires_clerk(client, seeded):
    login(client, "Shop B", "rep1")  # verifier role
    r = client.post("/customers", json=enrol_body())
    assert r.status_code == 403


def test_consent_required(client, seeded):
    login(client, "Bank A", "clerk1")
    r = client.post("/customers", json=enrol_body(granted=False))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_full_enrolment_happy_path(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client)
    from backend.app.models_db import ConsentRecord, Customer, ReferenceSignature
    with session_factory() as db:
        cust = db.get(Customer, cust_id)
        assert cust is not None and cust.enrolled_by_org_id == seeded["bank"]
        refs = db.query(ReferenceSignature).filter_by(customer_id=cust_id).all()
        assert 5 <= len(refs) <= 10
        assert all(len(r.embedding) == 512 for r in refs)  # 128 float32
        assert db.query(ConsentRecord).filter_by(customer_id=cust_id).count() == 1


def test_duplicate_customer(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456780")
    r = client.post("/customers", json=enrol_body("123456780"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_CUSTOMER"


def test_card_with_too_few_signatures(client, seeded):
    login(client, "Bank A", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456781")).json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(2), "image/jpeg")})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"


def test_approve_too_few_selected(client, seeded):
    login(client, "Bank A", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456782")).json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(6), "image/jpeg")})
    crop_ids = [c["crop_id"] for c in r.json()["crops"]][:3]
    r = client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"


def test_get_customer_scoped_to_enrolling_org(client, seeded):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456783")
    assert client.get(f"/customers/{cust_id}").status_code == 200
    # verifier of another org: forbidden by role
    client.cookies.clear()
    login(client, "Shop B", "rep1")
    assert client.get(f"/customers/{cust_id}").status_code == 403


def test_invalid_national_id_rejected(client, seeded):
    login(client, "Bank A", "clerk1")
    r = client.post("/customers", json=enrol_body("../../etc/passwd"))
    assert r.status_code == 422
