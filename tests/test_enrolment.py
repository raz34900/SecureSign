import io

from PIL import Image

from conftest import login
from test_signature_core import make_specimen_card


def enrol_body(nid: str = "123456780", granted: bool = True) -> dict:
    return {"national_id": nid, "full_name": "Test Person",
            "consent": {"granted": granted, "method": "signed_form"}}


def do_full_enrolment(client, nid: str = "123456780", card: bytes | None = None) -> str:
    """Returns customer_id. Assumes clerk already logged in."""
    r = client.post("/customers", json=enrol_body(nid))
    assert r.status_code == 200, r.text
    eid = r.json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", card or make_specimen_card(9), "image/jpeg")})
    assert r.status_code == 200, r.text
    crop_ids = [c["crop_id"] for c in r.json()["crops"]][:9]
    r = client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})
    assert r.status_code == 200, r.text
    return r.json()["customer_id"]


def test_enrolment_requires_clerk(client, seeded):
    login(client, "SB44", "rep1")  # verifier role
    r = client.post("/customers", json=enrol_body())
    assert r.status_code == 403


def test_consent_required(client, seeded):
    login(client, "BA11", "clerk1")
    r = client.post("/customers", json=enrol_body(granted=False))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_full_enrolment_happy_path(client, seeded, session_factory):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client)
    from backend.app.models_db import ConsentRecord, Customer, ReferenceSignature
    with session_factory() as db:
        cust = db.get(Customer, cust_id)
        assert cust is not None and cust.enrolled_by_org_id == seeded["bank"]
        refs = db.query(ReferenceSignature).filter_by(customer_id=cust_id).all()
        assert len(refs) == 9
        assert all(len(r.embedding) == 512 for r in refs)  # 128 float32
        assert db.query(ConsentRecord).filter_by(customer_id=cust_id).count() == 1


def test_existing_national_id_stages_append_mode(client, seeded):
    """A second enrolment of a known identifier is no longer a conflict: it stages an
    append, and the submitted signatures are checked against the existing references."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456780")
    r = client.post("/customers", json=enrol_body("123456780"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "append"
    assert body["enrolment_id"]


def test_new_national_id_stages_new_mode(client, seeded):
    login(client, "BA11", "clerk1")
    r = client.post("/customers", json=enrol_body("123456779"))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "new"


def test_card_with_fewer_than_eight_signatures(client, seeded):
    """Five references were measured at roughly 20% false rejection, so eight is the floor.

    The floor is enforced where it belongs — on approval, against the running total.
    Enforcing it per photograph made a short card a dead end: the clerk could only
    re-shoot the whole thing, and a card that groups two signatures never comes out
    right no matter the angle.
    """
    login(client, "BA11", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456784")).json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(7), "image/jpeg")})
    assert r.status_code == 200, "a short photograph is progress, not a failure"
    crop_ids = [c["crop_id"] for c in r.json()["crops"]]
    assert len(crop_ids) == 7

    approved = client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})
    assert approved.status_code == 422
    assert approved.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"
    assert "8" in approved.json()["error"]["message"]


def test_a_photograph_yielding_nothing_is_still_refused(client, seeded):
    """Accumulating does not mean accepting anything: a photograph that contributes no
    signature at all is refused, so the clerk is told rather than left wondering."""
    login(client, "BA11", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456781")).json()["enrolment_id"]
    blank = io.BytesIO()
    Image.new("L", (900, 700), 255).convert("RGB").save(blank, format="JPEG")
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("blank.jpg", blank.getvalue(), "image/jpeg")})
    assert r.status_code == 422


def test_approve_too_few_selected(client, seeded):
    login(client, "BA11", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456782")).json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.jpg", make_specimen_card(9), "image/jpeg")})
    crop_ids = [c["crop_id"] for c in r.json()["crops"]][:3]
    r = client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"


def test_get_customer_scoped_to_enrolling_org(client, seeded):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456783")
    assert client.get(f"/customers/{cust_id}").status_code == 200
    # verifier of another org: forbidden by role
    client.cookies.clear()
    login(client, "SB44", "rep1")
    assert client.get(f"/customers/{cust_id}").status_code == 403


def test_invalid_national_id_rejected(client, seeded):
    login(client, "BA11", "clerk1")
    r = client.post("/customers", json=enrol_body("../../etc/passwd"))
    assert r.status_code == 422


def test_photographs_accumulate_instead_of_replacing(client, seeded):
    """The loop the clerk was stuck in. A card photographed at an angle groups two
    signatures into one region or loses one at the edge, and re-shooting the whole card
    to fix a single specimen never converges. Each photograph now contributes what it
    yields, and the minimum applies to the running total."""
    login(client, "BA11", "clerk1")
    enrolment_id = client.post("/customers", json=enrol_body("123456700")).json()["enrolment_id"]

    first = client.post(f"/customers/{enrolment_id}/card",
                        files={"file": ("a.jpg", make_specimen_card(4), "image/jpeg")})
    assert first.status_code == 200, first.text
    assert len(first.json()["crops"]) == 4

    second = client.post(f"/customers/{enrolment_id}/card",
                         files={"file": ("b.jpg", make_specimen_card(5, variant=1), "image/jpeg")})
    assert second.status_code == 200, second.text
    crops = second.json()["crops"]
    assert len(crops) == 9, "the second photograph replaced the first instead of adding"

    # The first photograph's crop ids survive, so a selection made against them holds.
    assert {c["crop_id"] for c in first.json()["crops"]} < {c["crop_id"] for c in crops}


def test_a_short_photograph_is_no_longer_a_dead_end(client, seeded):
    """Four signatures is under the floor of eight, but it is progress, not a failure."""
    login(client, "BA11", "clerk1")
    enrolment_id = client.post("/customers", json=enrol_body("123456701")).json()["enrolment_id"]

    assert client.post(f"/customers/{enrolment_id}/card",
                       files={"file": ("a.jpg", make_specimen_card(4), "image/jpeg")}
                       ).status_code == 200
    crops = client.post(f"/customers/{enrolment_id}/card",
                        files={"file": ("b.jpg", make_specimen_card(4, variant=1), "image/jpeg")}
                        ).json()["crops"]
    assert len(crops) == 8

    approved = client.post(f"/customers/{enrolment_id}/references",
                           json={"crop_ids": [c["crop_id"] for c in crops]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["reference_count"] == 8


def test_a_photograph_with_no_signature_keeps_what_was_collected(client, seeded):
    login(client, "BA11", "clerk1")
    enrolment_id = client.post("/customers", json=enrol_body("123456702")).json()["enrolment_id"]
    client.post(f"/customers/{enrolment_id}/card",
                files={"file": ("a.jpg", make_specimen_card(9), "image/jpeg")})

    blank = io.BytesIO()
    Image.new("L", (900, 700), 255).convert("RGB").save(blank, format="JPEG")
    rejected = client.post(f"/customers/{enrolment_id}/card",
                           files={"file": ("blank.jpg", blank.getvalue(), "image/jpeg")})
    assert rejected.status_code == 422

    kept = client.post(f"/customers/{enrolment_id}/card",
                       files={"file": ("c.jpg", make_specimen_card(1, variant=1), "image/jpeg")})
    assert len(kept.json()["crops"]) == 10, "the failed photograph discarded the good ones"


def test_staged_crops_are_bounded(client, seeded):
    """Accumulating across photographs must not accumulate without limit."""
    from backend.app.services.enrolment import MAX_STAGED_CROPS

    login(client, "BA11", "clerk1")
    enrolment_id = client.post("/customers", json=enrol_body("123456703")).json()["enrolment_id"]
    for attempt in range(6):
        response = client.post(f"/customers/{enrolment_id}/card",
                               files={"file": ("c.jpg", make_specimen_card(10, variant=attempt),
                                               "image/jpeg")})
        if response.status_code != 200:
            assert response.json()["error"]["code"] == "TOO_MANY_SIGNATURES"
            break
        assert len(response.json()["crops"]) <= MAX_STAGED_CROPS
