from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def test_history_scoped_to_own_org(client, seeded):
    login(client, "Bank A", "clerk1")
    do_full_enrolment(client, "123456785")
    verify(client, "123456785", png(make_signature()))          # bank's verification
    client.cookies.clear()
    login(client, "Shop B", "rep1")
    verify(client, "123456785", png(make_signature(seed=9)))    # shop's verification
    r = client.get("/verifications")
    assert r.status_code == 200
    items = r.json()["verifications"]
    assert len(items) == 1  # only Shop B's own — Bank A's is invisible
    assert set(items[0].keys()) == {"request_id", "verdict", "distance",
                                    "confidence", "model_version", "created_at"}


def test_history_requires_auth(client, seeded):
    assert client.get("/verifications").status_code == 401
