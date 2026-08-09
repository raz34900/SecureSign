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
    """Deterministic embedding from image bytes - no torch involved."""

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
    from backend.app.services import enrolment as enrolment_service
    enrolment_service._store.clear()

    return create_app(session_factory=session_factory, embedder=FakeEmbedder())


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded(session_factory):
    """3 orgs, 3 users. Password for all: 'pw123456'."""
    with session_factory() as db:
        op = Organisation(name="SecureSign Ltd", type="operator")
        bank = Organisation(name="Bank A", type="financial")
        shop = Organisation(name="Shop B", type="subscriber")
        db.add_all([op, bank, shop])
        db.flush()
        pw = hash_password("pw123456")
        db.add_all([
            User(org_id=bank.id, username="clerk1", password_hash=pw, role="clerk"),
            User(org_id=shop.id, username="rep1", password_hash=pw, role="verifier"),
            User(org_id=op.id, username="eng1", password_hash=pw, role="engineer"),
        ])
        db.commit()
        return {"op": op.id, "bank": bank.id, "shop": shop.id}


def login(client, org_name: str, username: str, password: str = "pw123456"):
    return client.post("/auth/login", json={"org_name": org_name, "username": username, "password": password})
