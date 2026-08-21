"""Injection probes against every field that takes free text.

Every query in this project goes through SQLAlchemy with bound parameters, so a payload
should be stored and returned as the literal characters someone typed. That is the claim;
this file is the evidence, and it fails loudly if anyone ever hand-builds a query string.

The LIKE searches get their own attention. Parameter binding stops SQL injection there but
does not stop *wildcard* injection: `%` and `_` are metacharacters to LIKE itself, so an
unescaped search term can match far more than it appears to ask for.
"""
from conftest import login
from test_engineering import enter_panel
from test_org_admin import owner_password

STRONG = "correct-horse-battery"

PAYLOADS = [
    "Bank Hapoalim' 1=1 --",
    "Bank Hapoalim' OR '1'='1",
    "x'; DROP TABLE organisations; --",
    "x\" OR \"\"=\"",
    "Robert'); DROP TABLE users; --",
    "' UNION SELECT password_hash FROM users --",
    "100%_wildcard",
]


def org_names(client) -> dict[str, str]:
    return {org["code"]: org["name"]
            for org in client.get("/admin/organisations").json()["organisations"]}


def test_an_organisation_name_is_stored_as_typed(client, seeded):
    """Not escaped, not stripped, not executed — stored verbatim and read back verbatim."""
    enter_panel(client)
    for index, payload in enumerate(PAYLOADS):
        code = f"INJ{index}"
        created = client.post("/admin/organisations",
                              json={"code": code, "name": payload, "type": "subscriber"})
        assert created.status_code == 200, f"{payload!r}: {created.text}"
        assert created.json()["name"] == payload
        assert org_names(client)[code] == payload


def test_a_rename_cannot_execute_anything(client, seeded):
    enter_panel(client)
    for payload in PAYLOADS:
        result = client.post("/admin/organisations/BA11/name", json={"name": payload})
        assert result.status_code == 200, f"{payload!r}: {result.text}"
        assert result.json()["name"] == payload

    # The tables an injected statement would have targeted are all still there.
    assert org_names(client)["BB22"]
    assert client.get("/admin/users").json()["total"] >= 1


def test_the_account_search_binds_its_parameter(client, seeded):
    """`' OR '1'='1` is a string to match, not a condition to evaluate. It matches
    nothing, because no username or organisation contains those characters."""
    enter_panel(client)
    before = client.get("/admin/users").json()["total"]

    for payload in ("' OR '1'='1", "x'; DROP TABLE users; --", "' UNION SELECT 1 --"):
        body = client.get("/admin/users", params={"q": payload}).json()
        assert body["total"] == 0, f"{payload!r} matched {body['total']} accounts"

    assert client.get("/admin/users").json()["total"] == before, "the table survived"


def test_a_search_term_cannot_smuggle_a_like_wildcard(client, seeded):
    """Binding stops SQL injection but not LIKE's own metacharacters. A search for `%`
    must mean the character, or a search box quietly becomes "show me everything"."""
    enter_panel(client)
    total = client.get("/admin/users").json()["total"]
    assert total > 1, "fixture assumption: more than one account exists"

    for wildcard in ("%", "_", "%%", "%a%"):
        matched = client.get("/admin/users", params={"q": wildcard}).json()["total"]
        assert matched < total, f"{wildcard!r} matched every account ({matched}/{total})"


def test_a_search_finds_a_name_that_contains_a_wildcard(client, seeded):
    """The other half of escaping: a literal % in a name must still be findable."""
    enter_panel(client)
    client.post("/admin/organisations",
                json={"code": "PCT1", "name": "100% Credit Union", "type": "subscriber"})
    client.post("/admin/users", json={"org_code": "PCT1", "username": "pctuser",
                                      "role": "verifier"})

    found = client.get("/admin/users", params={"q": "100% Credit"}).json()
    assert [u["username"] for u in found["users"]] == ["pctuser"]


def test_a_national_id_filter_cannot_be_injected(client, seeded):
    """Constrained by pattern before it reaches the database, so this is defence in
    depth — but the check belongs here, because the pattern is one edit from changing."""
    login(client, "BA11", "clerk1")
    for payload in ("1' OR '1'='1", "123456789'--", "%"):
        assert client.get("/verifications", params={"national_id": payload}).status_code == 422


def test_an_injected_name_survives_a_round_trip_through_the_org_admin_panel(client, seeded):
    """The scoped panel reads the same rows; a payload stored by the operator must not
    change meaning when a different endpoint renders it."""
    from test_org_admin import make_admin

    enter_panel(client)
    client.post("/admin/organisations/BA11/name", json={"name": "Bank' OR 1=1 --"})
    client.cookies.clear()

    make_admin(client, "BA11", "boss1")
    client.cookies.clear()
    login(client, "BA11", "boss1", password=owner_password("boss1"))
    assert client.get("/org/users").json()["organisation"]["name"] == "Bank' OR 1=1 --"
