import logging

from fastapi import FastAPI

from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app.errors import install_error_handlers
from backend.app import models_db  # noqa: F401  — registers ORM tables

log = logging.getLogger("securesign")


def create_app(session_factory=None, embedder=None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SecureSign", version="0.1.0")
    install_error_handlers(app)

    if session_factory is None:
        for key in (settings.pii_enc_key, settings.pii_index_key):
            if len(key) != 64:
                raise RuntimeError("SS_PII_ENC_KEY / SS_PII_INDEX_KEY must be 32-byte hex strings")
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)
        session_factory = make_session_factory(engine)
    if embedder is None:
        from signature_core.embed import Embedder
        embedder = Embedder.load(settings.model_path)
        log.info("model loaded: %s (%s)", settings.model_version, settings.model_path)

    app.state.session_factory = session_factory
    app.state.embedder = embedder

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model_version": settings.model_version,
                "model_loaded": app.state.embedder is not None}

    from backend.app.routers import auth as auth_router          # Task 6
    from backend.app.routers import customers as customers_router  # Task 7
    app.include_router(auth_router.router)
    app.include_router(customers_router.router)
    return app
