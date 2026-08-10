"""Per-org reference ownership: append-mode enrolment, the anti-impersonation guard,
reference deletion rules, national-id lookup, and the clerk-only verify breakdown."""
import io

import numpy as np
from PIL import Image

from conftest import FakeEmbedder, login
from test_enrolment import enrol_body, do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify
from signature_core.anchors import extract_vertical_anchors


def _card(seeds: list[int]) -> bytes:
    """Specimen card built from explicit signatures - one row per seed."""
    card = Image.new("L", (800, 1200), 255)
    for row, seed in enumerate(seeds):
        card.paste(make_signature(seed=seed, size=(500, 150)), (150, 60 + row * 180))
    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()


UNIFORM_CARD = _card([5] * 6)
# Six different writers: unit vectors pointing elsewhere, distance ~sqrt(2).
DIFFERENT_CARD = _card([11, 12, 13, 14, 15, 16])


def append_card(client, nid: str, card: bytes):
    """Stage + upload + approve against an already-registered national id."""
    r = client.post("/customers", json=enrol_body(nid))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "append"
    eid = r.json()["enrolment_id"]
    r = client.post(f"/customers/{eid}/card",
                    files={"file": ("card.png", card, "image/png")})
    assert r.status_code == 200, r.text
    crop_ids = [c["crop_id"] for c in r.json()["crops"]][:6]
    return client.post(f"/customers/{eid}/references", json={"crop_ids": crop_ids})


def refs_of(session_factory, customer_id: str, org_id: str | None = None):
    from backend.app.models_db import ReferenceSignature
    with session_factory() as db:
        q = db.query(ReferenceSignature).filter_by(customer_id=customer_id)
        if org_id is not None:
            q = q.filter_by(org_id=org_id)
        return q.all()


# --- append mode -----------------------------------------------------------


def test_append_mode_gives_second_org_its_own_references(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456700", card=UNIFORM_CARD)
    assert len(refs_of(session_factory, cust_id, seeded["bank"])) >= 5
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    r = append_card(client, "123456700", UNIFORM_CARD)
    assert r.status_code == 200, r.text
    assert r.json()["customer_id"] == cust_id

    own = refs_of(session_factory, cust_id, seeded["bank2"])
    assert len(own) >= 5
    assert all(ref.org_id == seeded["bank2"] for ref in own)
    # Bank A's set is untouched; consent is recorded per org.
    assert len(refs_of(session_factory, cust_id, seeded["bank"])) >= 5
    from backend.app.models_db import AuditLog, ConsentRecord
    with session_factory() as db:
        assert db.query(ConsentRecord).filter_by(
            customer_id=cust_id, org_id=seeded["bank2"]).count() == 1
        assert db.query(AuditLog).filter_by(
            action="enrol_append", outcome="allowed", resource_id=cust_id).count() == 1


def test_append_mode_second_org_can_manage_its_references(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456701", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    assert append_card(client, "123456701", UNIFORM_CARD).status_code == 200
    r = client.get(f"/customers/{cust_id}/references")
    assert r.status_code == 200, r.text
    own_ids = {ref.id for ref in refs_of(session_factory, cust_id, seeded["bank2"])}
    assert {ref["reference_id"] for ref in r.json()["references"]} == own_ids


def test_append_mode_rejects_signatures_of_another_writer(client, seeded, session_factory):
    embedder = FakeEmbedder()
    enrolled = embedder.embed(extract_vertical_anchors(UNIFORM_CARD)[0])
    foreign = embedder.embed(extract_vertical_anchors(DIFFERENT_CARD)[0])
    assert float(np.linalg.norm(enrolled - foreign)) > 0.3999  # precondition: a FRAUD distance

    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456702", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    r = append_card(client, "123456702", DIFFERENT_CARD)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SIGNATURE_MISMATCH"

    assert refs_of(session_factory, cust_id, seeded["bank2"]) == []
    from backend.app.models_db import AuditLog, ConsentRecord
    with session_factory() as db:
        assert db.query(ConsentRecord).filter_by(
            customer_id=cust_id, org_id=seeded["bank2"]).count() == 0
        assert db.query(AuditLog).filter_by(
            action="enrol_append", outcome="denied", resource_id=cust_id).count() == 1


def test_append_mode_respects_per_org_ceiling(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456703", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    assert append_card(client, "123456703", UNIFORM_CARD).status_code == 200  # 6 owned
    r = append_card(client, "123456703", UNIFORM_CARD)  # 6 more would exceed 10
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "TOO_MANY_SIGNATURES"


# --- reference deletion ----------------------------------------------------


def test_other_org_cannot_delete_a_reference(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456704")
    ref_id = refs_of(session_factory, cust_id, seeded["bank"])[0].id
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    r = client.delete(f"/customers/{cust_id}/references/{ref_id}")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Customer not found."
    assert any(ref.id == ref_id for ref in refs_of(session_factory, cust_id))


def test_owner_deletes_reference_above_the_floor(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456705")
    refs = refs_of(session_factory, cust_id, seeded["bank"])
    assert len(refs) == 6

    r = client.delete(f"/customers/{cust_id}/references/{refs[0].id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": refs[0].id}
    assert len(refs_of(session_factory, cust_id, seeded["bank"])) == 5

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(
            action="delete_reference", resource_id=refs[0].id).count() == 1


def test_deleting_below_the_floor_is_rejected(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456706")
    refs = refs_of(session_factory, cust_id, seeded["bank"])
    assert client.delete(f"/customers/{cust_id}/references/{refs[0].id}").status_code == 200

    r = client.delete(f"/customers/{cust_id}/references/{refs[1].id}")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "REFERENCE_FLOOR"
    assert len(refs_of(session_factory, cust_id, seeded["bank"])) == 5


# --- lookup by national id -------------------------------------------------


def test_lookup_by_national_id_for_owning_org(client, seeded):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456707")
    r = client.get("/customers/lookup/123456707")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_id"] == cust_id
    assert body["full_name"] == "Test Person"
    assert body["status"] == "active"
    assert body["own_reference_count"] == 6
    assert body["created_at"]


def test_lookup_hidden_from_org_without_references(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456708")
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    r = client.get("/customers/lookup/123456708")
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Customer not found."
    assert r.json() == client.get("/customers/lookup/999999998").json()


def test_lookup_visible_once_an_org_owns_references(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456709", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    assert append_card(client, "123456709", UNIFORM_CARD).status_code == 200
    r = client.get("/customers/lookup/123456709")
    assert r.status_code == 200, r.text
    assert r.json()["own_reference_count"] == 6


def test_lookup_forbidden_for_verifier(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456710")
    client.cookies.clear()

    login(client, "Shop B", "rep1")
    assert client.get("/customers/lookup/123456710").status_code == 403


# --- verify breakdown ------------------------------------------------------


def test_clerk_verify_includes_per_anchor_references(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456711", card=UNIFORM_CARD)
    r = verify(client, "123456711", png(make_signature(seed=5, size=(500, 150))))
    assert r.status_code == 200, r.text
    body = r.json()

    ref_ids = {ref.id for ref in refs_of(session_factory, cust_id)}
    assert {ref["reference_id"] for ref in body["references"]} == ref_ids
    for ref in body["references"]:
        import base64
        assert base64.b64decode(ref["image_png_base64"]).startswith(b"\x89PNG")
        assert ref["passed"] == (ref["distance"] < body["threshold"])
        assert 0.0 <= ref["confidence"] <= 99.9

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(
            action="view_references", outcome="allowed", resource_id=cust_id).count() == 1


def test_verifier_verify_has_no_references_key(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456712", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Shop B", "rep1")
    r = verify(client, "123456712", png(make_signature(seed=5, size=(500, 150))))
    assert r.status_code == 200, r.text
    assert "references" not in r.json()


# --- customer soft delete --------------------------------------------------


def test_enrolling_org_soft_deletes_customer(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456713")

    r = client.delete(f"/customers/{cust_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": cust_id}

    from backend.app.models_db import AuditLog, Customer
    with session_factory() as db:
        assert db.get(Customer, cust_id).status == "deleted"
        assert db.query(AuditLog).filter_by(
            action="delete_customer", resource_id=cust_id).count() == 1

    assert client.get(f"/customers/{cust_id}").status_code == 404
    assert verify(client, "123456713", png(make_signature())).status_code == 404


def test_non_enrolling_org_cannot_delete_customer(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456714", card=UNIFORM_CARD)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    assert append_card(client, "123456714", UNIFORM_CARD).status_code == 200
    r = client.delete(f"/customers/{cust_id}")  # owns references, but did not enrol
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Customer not found."

    from backend.app.models_db import Customer
    with session_factory() as db:
        assert db.get(Customer, cust_id).status == "active"


# --- reference counts after the per-customer rule change -----------------------


def test_existing_customer_may_be_topped_up_with_a_single_signature(client, seeded, session_factory):
    """A customer already on file has met the five-signature bar, so a second
    institution can contribute whatever it managed to capture."""
    card = _card([5] * 6)
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456720", card=card)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    staged = client.post("/customers", json={
        "national_id": "123456720", "full_name": "Top Up",
        "consent": {"granted": True, "method": "in_person"}}).json()
    assert staged["mode"] == "append"

    crops = client.post(f"/customers/{staged['enrolment_id']}/card",
                        files={"file": ("card.jpg", card, "image/jpeg")}).json()["crops"]
    r = client.post(f"/customers/{staged['enrolment_id']}/references",
                    json={"crop_ids": [crops[0]["crop_id"]]})
    assert r.status_code == 200, r.text
    assert len(refs_of(session_factory, cust_id, seeded["bank2"])) == 1


def test_a_thin_card_is_accepted_when_topping_up_but_not_when_enrolling(client, seeded):
    """The full specimen card is only demanded for a customer nobody holds yet."""
    thin = _card([5, 5])
    login(client, "Bank A", "clerk1")

    fresh = client.post("/customers", json={
        "national_id": "123456721", "full_name": "Fresh",
        "consent": {"granted": True, "method": "signed_form"}}).json()["enrolment_id"]
    rejected = client.post(f"/customers/{fresh}/card",
                           files={"file": ("card.jpg", thin, "image/jpeg")})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"

    do_full_enrolment(client, "123456722", card=_card([5] * 6))
    client.cookies.clear()
    login(client, "Bank B", "clerk2")
    staged = client.post("/customers", json={
        "national_id": "123456722", "full_name": "Fresh",
        "consent": {"granted": True, "method": "in_person"}}).json()["enrolment_id"]
    accepted = client.post(f"/customers/{staged}/card",
                           files={"file": ("card.jpg", thin, "image/jpeg")})
    assert accepted.status_code == 200, accepted.text


def test_an_org_may_remove_its_own_while_another_org_keeps_the_customer_verifiable(
        client, seeded, session_factory):
    card = _card([5] * 6)
    login(client, "Bank A", "clerk1")
    cust_id = do_full_enrolment(client, "123456723", card=card)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    staged = client.post("/customers", json={
        "national_id": "123456723", "full_name": "Shared",
        "consent": {"granted": True, "method": "in_person"}}).json()["enrolment_id"]
    crops = client.post(f"/customers/{staged}/card",
                        files={"file": ("card.jpg", card, "image/jpeg")}).json()["crops"]
    client.post(f"/customers/{staged}/references",
                json={"crop_ids": [c["crop_id"] for c in crops[:2]]})

    for ref in refs_of(session_factory, cust_id, seeded["bank2"]):
        assert client.delete(
            f"/customers/{cust_id}/references/{ref.id}").status_code == 200
    assert refs_of(session_factory, cust_id, seeded["bank2"]) == []


def test_the_customer_wide_ceiling_is_enforced(client, seeded, monkeypatch):
    """Separation stops improving well before this point, so the cap only bounds
    storage and per-verification work."""
    from backend.app.services import enrolment as enrolment_service

    monkeypatch.setattr(enrolment_service, "MAX_CUSTOMER_REFS", 7)
    card = _card([5] * 6)
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456724", card=card)
    client.cookies.clear()

    login(client, "Bank B", "clerk2")
    staged = client.post("/customers", json={
        "national_id": "123456724", "full_name": "Capped",
        "consent": {"granted": True, "method": "in_person"}}).json()["enrolment_id"]
    crops = client.post(f"/customers/{staged}/card",
                        files={"file": ("card.jpg", card, "image/jpeg")}).json()["crops"]

    r = client.post(f"/customers/{staged}/references",
                    json={"crop_ids": [c["crop_id"] for c in crops[:5]]})  # 6 + 5 > 7
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TOO_MANY_SIGNATURES"
