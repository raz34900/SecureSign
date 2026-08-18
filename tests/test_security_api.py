from pathlib import Path

from conftest import login
from test_signature_core import make_signature
from test_verify import png, verify

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_missing_credentials_everywhere(client, seeded):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/customers", json={}).status_code == 401
    assert client.get("/verifications").status_code == 401


def test_invalid_session_cookie(client, seeded):
    client.cookies.set("session", "forged-token-value")
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID"


def test_path_traversal_in_national_id(client, seeded):
    login(client, "SB44", "rep1")
    r = verify(client, "../../etc/passwd", png(make_signature()))
    assert r.status_code == 422  # rejected by ^\d{9}$ validation


def test_oversized_upload(client, seeded):
    login(client, "SB44", "rep1")
    big = b"\x00" * (11 * 1024 * 1024)  # 11 MB > 10 MB cap
    r = client.post("/verify", data={"national_id": "123456789"},
                    files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_error_messages_leak_nothing(client, seeded):
    login(client, "SB44", "rep1")
    r = verify(client, "999999997", png(make_signature()))
    msg = r.json()["error"]["message"]
    for fragment in ("/Users", "/home", "Traceback", ".py", "sqlite", "SELECT"):
        assert fragment not in msg


def test_the_interface_never_names_the_internal_entrypoint():
    """The public bundle is served to anyone. It once told a 404'd visitor that the
    engineering panel was internal only and gave its exact address, which is the
    deployment topology handed to the one reader who must not have it. The internal
    address must not appear in any shipped source file."""
    for path in (REPO_ROOT / "frontend" / "src").rglob("*"):
        if path.suffix not in (".vue", ".js", ".mjs"):
            continue
        source = path.read_text()
        assert "8081" not in source, f"{path.name} names the internal port"
        assert "internal only" not in source.lower(), f"{path.name} describes the topology"


def test_denied_cross_role_lands_in_audit(client, seeded, session_factory):
    login(client, "SB44", "rep1")  # verifier tries clerk-only endpoint
    r = client.post("/customers", json={"national_id": "123456786", "full_name": "X",
                                        "consent": {"granted": True, "method": "in_person"}})
    assert r.status_code == 403
    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(outcome="denied").count() >= 1
