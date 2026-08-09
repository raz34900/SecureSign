import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, make_engine, make_session_factory


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
def app(session_factory, monkeypatch):
    monkeypatch.setenv("SS_PII_ENC_KEY", "aa" * 32)
    monkeypatch.setenv("SS_PII_INDEX_KEY", "bb" * 32)
    from backend.app.config import get_settings
    get_settings.cache_clear()
    from backend.app.main import create_app
    return create_app(session_factory=session_factory, embedder=FakeEmbedder())


@pytest.fixture
def client(app):
    return TestClient(app)
