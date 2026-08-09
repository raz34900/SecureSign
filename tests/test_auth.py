from conftest import login


def test_login_sets_cookie_and_me(client, seeded):
    r = login(client, "Bank A", "clerk1")
    assert r.status_code == 200
    assert r.json() == {"role": "clerk", "org_type": "financial"}
    assert "session" in client.cookies
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "clerk1"


def test_login_bad_password_generic_message(client, seeded):
    r = login(client, "Bank A", "clerk1", password="wrong")
    assert r.status_code == 401
    # generic - must not reveal whether username exists (book 6.2.1 2.a)
    assert "clerk1" not in r.json()["error"]["message"]
    r2 = login(client, "Bank A", "ghost")
    assert r2.json()["error"]["message"] == r.json()["error"]["message"]


def test_me_without_session(client, seeded):
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_logout_revokes(client, seeded):
    login(client, "Bank A", "clerk1")
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401
