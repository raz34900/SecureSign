import base64

from conftest import login
from test_enrolment import do_full_enrolment


def test_clerk_own_org_can_view_references(client, seeded):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456790")
    r = client.get(f"/customers/{cust_id}/references")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_id"] == cust_id
    assert len(body["references"]) >= 5
    for ref in body["references"]:
        png_bytes = base64.b64decode(ref["image_png_base64"])
        assert png_bytes.startswith(b"\x89PNG")


def test_clerk_other_org_gets_404(client, seeded):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456791")
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    r = client.get(f"/customers/{cust_id}/references")
    assert r.status_code == 404


def test_verifier_forbidden(client, seeded):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456792")
    client.cookies.clear()

    login(client, "SB44", "rep1")
    r = client.get(f"/customers/{cust_id}/references")
    assert r.status_code == 403


def test_audit_row_written_on_success(client, seeded, session_factory):
    login(client, "BA11", "clerk1")
    cust_id = do_full_enrolment(client, "123456793")
    r = client.get(f"/customers/{cust_id}/references")
    assert r.status_code == 200

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(
            action="view_references", outcome="allowed", resource_id=cust_id).count() >= 1
