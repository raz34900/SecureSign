import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool

from backend.app.auth.passwords import hash_password
from backend.app.db import Base, make_engine, make_session_factory
from backend.app.models_db import Organisation, User


class FakeEmbedder:
    """Deterministic embedding from image bytes — no torch involved."""

    def embed(self, img: Image.Image) -> np.ndarray:
        digest = hashlib.sha256(img.convert("L").resize((32, 32)).tobytes()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        v = rng.normal(size=128).astype(np.float32)
        return v / np.linalg.norm(v)


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def app(session_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("SS_PII_ENC_KEY", "aa" * 32)
    monkeypatch.setenv("SS_PII_INDEX_KEY", "bb" * 32)
    from backend.app.config import get_settings
    get_settings.cache_clear()
    from backend.app.main import create_app

    import backend.app.routers.customers as customers_router_module
    customers_router_module.SAMPLES_DIR = str(tmp_path / "samples")
    from backend.app.services import verification as verification_module
    monkeypatch.setattr(verification_module, "QUERY_IMAGE_DIR",
                        str(tmp_path / "queries"))
    from backend.app.services import enrolment as enrolment_service
    enrolment_service._store.clear()

    return create_app(session_factory=session_factory, embedder=FakeEmbedder())


@pytest.fixture(autouse=True)
def _clean_login_throttle():
    """Failed sign-ins are counted per account in module state. Several tests sign in
    wrongly on purpose; without this they would spend each other's allowance."""
    from backend.app.auth import throttle
    throttle.reset()
    yield
    throttle.reset()


def make_client(app) -> TestClient:
    """https, not http: the session cookie is set Secure, and a client on a plain-http
    base URL silently drops it — the test then fails as 401 for the wrong reason.
    Build every client through here rather than calling TestClient directly."""
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def client(app):
    return make_client(app)


@pytest.fixture
def other_client(app):
    """A second, independent session against the same app — for tests where one account
    acts on another that is signed in at the same time."""
    return make_client(app)


@pytest.fixture
def seeded(session_factory):
    """5 orgs (2 financial, 2 subscriber, operator), 5 users. Password for all: 'pw123456'.

    Organisations log in by code (BA11), never by display name — see login() below.
    """
    with session_factory() as db:
        op = Organisation(code="SS00", name="SecureSign Ltd", type="operator")
        bank = Organisation(code="BA11", name="Bank A", type="financial")
        bank2 = Organisation(code="BB22", name="Bank B", type="financial")
        shop2 = Organisation(code="SA33", name="Shop A", type="subscriber")
        shop = Organisation(code="SB44", name="Shop B", type="subscriber")
        db.add_all([op, bank, bank2, shop, shop2])
        db.flush()
        pw = hash_password("pw123456")
        db.add_all([
            User(org_id=bank.id, username="clerk1", password_hash=pw, role="clerk"),
            User(org_id=bank2.id, username="clerk2", password_hash=pw, role="clerk"),
            User(org_id=shop.id, username="rep1", password_hash=pw, role="verifier"),
            User(org_id=shop2.id, username="rep2", password_hash=pw, role="verifier"),
            User(org_id=op.id, username="eng1", password_hash=pw, role="engineer"),
        ])
        db.commit()
        return {"op": op.id, "bank": bank.id, "bank2": bank2.id,
                "shop": shop.id, "shop2": shop2.id}


def login(client, org_code: str, username: str, password: str = "pw123456"):
    return client.post("/auth/login",
                       json={"org_code": org_code, "username": username, "password": password})
