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
