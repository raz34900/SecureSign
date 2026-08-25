def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model_version"]


def test_unknown_route_error_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert set(r.json()["error"].keys()) == {"code", "message"}


def test_ready_reports_database_and_model(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok" and body["model_loaded"] is True


def test_an_unreachable_database_is_a_503_with_retry_after(client, app):
    """Fail closed, and say which failure it is: 503 means "down, try again", 500 means
    "broken". The distinction is the whole point of the handler."""
    from sqlalchemy.exc import OperationalError
    from backend.app.auth import deps

    def dead_db():
        raise OperationalError("SELECT 1", None, ConnectionRefusedError("refused"))

    app.dependency_overrides[deps.get_db] = dead_db
    try:
        r = client.get("/verifications")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert r.headers.get("Retry-After") == "10"
    finally:
        app.dependency_overrides.pop(deps.get_db)


def test_shutdown_drain_is_bounded_and_compose_waits_longer():
    """uvicorn drains for 30s on SIGTERM; compose must not SIGKILL sooner, or a
    verification in flight is amputated mid-verdict on every redeploy."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "deploy" / "Dockerfile").read_text()
    assert "--timeout-graceful-shutdown" in dockerfile
    compose = (root / "docker-compose.yml").read_text()
    api_block = compose.split("  api:")[1].split("\n  db:")[0]
    assert "stop_grace_period: 40s" in api_block
