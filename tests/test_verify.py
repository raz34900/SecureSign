import io

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature


def png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify(client, nid: str, image_bytes: bytes):
    return client.post("/verify", data={"national_id": nid},
                       files={"file": ("sig.png", image_bytes, "image/png")})


def test_verify_unknown_customer_404_with_sanity(client, seeded):
    login(client, "Shop B", "rep1")
    r = verify(client, "999999998", png(make_signature()))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"
    assert "signature" in r.json()["error"]["message"].lower()


def test_verify_cross_org_returns_decision_only(client, seeded, session_factory):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456784")
    client.cookies.clear()
    login(client, "Shop B", "rep1")  # different org — cross-org verify allowed
    r = verify(client, "123456784", png(make_signature(seed=42)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"request_id", "national_id", "verdict", "distance",
                                "threshold", "confidence", "model_version", "verified_at"}
    assert body["verdict"] in ("VALID", "FRAUD")
    assert body["threshold"] == 0.3999
    # verification + audit rows persisted
    from backend.app.models_db import AuditLog, Verification
    with session_factory() as db:
        v = db.get(Verification, body["request_id"])
        assert v is not None and v.requesting_org_id == seeded["shop"]
        assert db.query(AuditLog).filter_by(action="verify", outcome="allowed").count() >= 1


def test_verify_blank_image_rejected(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456784")
    client.cookies.clear()
    login(client, "Shop B", "rep1")
    from PIL import Image
    r = verify(client, "123456784", png(Image.new("L", (300, 200), 255)))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_IMAGE"


def test_verify_forbidden_for_engineer(client, seeded):
    login(client, "SecureSign Ltd", "eng1")
    r = verify(client, "123456784", png(make_signature()))
    assert r.status_code == 403


def test_verify_requires_auth(client, seeded):
    r = verify(client, "123456784", png(make_signature()))
    assert r.status_code == 401
