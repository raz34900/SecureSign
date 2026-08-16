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
    login(client, "SB44", "rep1")
    r = verify(client, "999999998", png(make_signature()))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"
    assert "signature" in r.json()["error"]["message"].lower()


def test_verify_cross_org_returns_decision_only(client, seeded, session_factory):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456784")
    client.cookies.clear()
    login(client, "SB44", "rep1")  # different org - cross-org verify allowed
    r = verify(client, "123456784", png(make_signature(seed=42)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"request_id", "national_id", "verdict", "distance",
                                "threshold", "confidence", "model_version", "verified_at",
                                "query_preview_png_base64"}
    assert "references" not in body
    assert body["verdict"] in ("VALID", "FRAUD")
    assert body["threshold"] == 0.3999
    # verification + audit rows persisted
    from backend.app.models_db import AuditLog, Verification
    with session_factory() as db:
        v = db.get(Verification, body["request_id"])
        assert v is not None and v.requesting_org_id == seeded["shop"]
        assert db.query(AuditLog).filter_by(action="verify", outcome="allowed").count() >= 1


def test_verify_blank_image_rejected(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456784")
    client.cookies.clear()
    login(client, "SB44", "rep1")
    from PIL import Image
    r = verify(client, "123456784", png(Image.new("L", (300, 200), 255)))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_IMAGE"


def test_verify_forbidden_for_engineer(client, seeded):
    login(client, "SS00", "eng1")
    r = verify(client, "123456784", png(make_signature()))
    assert r.status_code == 403


def test_verify_requires_auth(client, seeded):
    r = verify(client, "123456784", png(make_signature()))
    assert r.status_code == 401


def test_query_preview_is_the_normalised_image_the_model_compared(client, seeded):
    """The clerk must see what was actually compared, not their own photograph, so a
    bad capture (shadow, fold, stray mark) is visible rather than hidden."""
    import base64
    import io as _io

    from PIL import Image as _Image

    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456790")
    body = verify(client, "123456790", png(make_signature(seed=11))).json()

    preview = _Image.open(_io.BytesIO(base64.b64decode(body["query_preview_png_base64"])))
    assert preview.size == (224, 224), "preview must be the model's input, not the upload"


def test_query_preview_reaches_the_subscriber_role_too(client, seeded):
    """It is the caller's own upload, so withholding it would help nobody."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456791")
    client.cookies.clear()
    login(client, "SB44", "rep1")
    body = verify(client, "123456791", png(make_signature(seed=12))).json()
    assert body["query_preview_png_base64"]
