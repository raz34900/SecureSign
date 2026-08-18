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


def test_the_session_cookie_is_not_allowed_out_in_the_clear(client, seeded):
    """Every entrypoint is TLS and port 80 only redirects, so there is no request this
    cookie legitimately rides unencrypted. Without Secure, one forced plaintext request
    to any port on the host hands over a live session."""
    header = login(client, "BA11", "clerk1").headers["set-cookie"].lower()
    assert "secure" in header
    assert "httponly" in header
    assert "samesite=lax" in header


def test_the_public_entrypoint_hides_the_generated_schema():
    """The four location blocks that hide the engineering and account routes are
    undone by /api/openapi.json, which names all of them along with their request
    shapes. Measured before this was closed: 30 paths served to the public listener,
    10 of them the ones the 404s exist to conceal."""
    public = (REPO_ROOT / "frontend" / "nginx.conf").read_text().split("listen 8081")[0]
    for path in ("/api/openapi.json", "/api/docs", "/api/redoc",
                 "/api/engineering", "/api/admin", "/engineering", "/accounts"):
        assert f"location {path} {{ return 404; }}" in public, f"{path} reachable publicly"


def test_the_api_is_not_published_on_the_host():
    """A published API port is a second door with no nginx on it: the engineering and
    account endpoints are hidden by an nginx rule, and a request that never passes
    through nginx never meets it. nginx reaches the API over the compose network."""
    compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text()
    api_block = compose.split("  api:")[1].split("\n  #")[0]
    assert "8000:8000" not in api_block
    assert "expose:" in api_block


def test_denied_cross_role_lands_in_audit(client, seeded, session_factory):
    login(client, "SB44", "rep1")  # verifier tries clerk-only endpoint
    r = client.post("/customers", json={"national_id": "123456786", "full_name": "X",
                                        "consent": {"granted": True, "method": "in_person"}})
    assert r.status_code == 403
    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(outcome="denied").count() >= 1


def test_the_security_headers_survive_the_add_header_trap():
    """nginx does not merge add_header: a location that declares one discards every
    header inherited from the server block. Both static locations set Cache-Control, so
    the page users actually load was sending no HSTS at all — only /api/ ever got it.
    Every block that sets a header of its own must pull the common set back in."""
    static = (REPO_ROOT / "frontend" / "nginx-static.inc").read_text()
    assert static.count("add_header") == static.count("securesign-headers.inc"), \
        "a location sets a header without re-including the common set"

    headers = (REPO_ROOT / "frontend" / "nginx-headers.inc").read_text()
    for header in ("Strict-Transport-Security", "X-Content-Type-Options",
                   "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy"):
        assert header in headers

    # The photograph preview is a createObjectURL of the picked File, and prepared
    # regions arrive as base64. A policy without both silently blanks both previews.
    assert "img-src 'self' data: blob:" in headers
    assert "script-src 'self';" in headers


def test_the_http_listener_will_not_redirect_to_an_attacker_chosen_host():
    """`return 301 https://$host...` reflects whatever Host arrived, so a cache in front
    can be poisoned with a Location pointing anywhere. Only names this deployment
    answers on get a redirect; the default server closes the connection."""
    public = (REPO_ROOT / "frontend" / "nginx.conf").read_text()
    listener = public.split("listen 443")[0]
    assert "listen 80 default_server;" in listener
    assert "return 444;" in listener
    assert "server_name localhost" in listener
