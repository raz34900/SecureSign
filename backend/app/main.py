import logging

from fastapi import FastAPI

from backend.app.config import get_settings
from backend.app.db import Base, make_engine, make_session_factory
from backend.app import migrate
from backend.app.errors import AppError, install_error_handlers
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
        migrate.apply(engine)
        session_factory = make_session_factory(engine)
    if embedder is None:
        from signature_core.embed import Embedder
        embedder = Embedder.load(settings.model_path)
        log.info("model loaded: %s (%s)", settings.model_version, settings.model_path)

    app.state.session_factory = session_factory
    app.state.embedder = embedder

    @app.get("/health")
    def health() -> dict:
        # Liveness: is the process alive. Deliberately no database check - a restart
        # cannot fix a dead database, and a liveness probe that includes one turns a
        # database outage into a restart storm on top of it.
        return {"status": "ok", "model_version": settings.model_version,
                "model_loaded": app.state.embedder is not None}

    @app.get("/ready")
    def ready() -> dict:
        # Readiness: can this instance actually serve. This is what a monitor or a
        # load balancer should watch; the OperationalError handler turns an unreachable
        # database into the 503 it deserves.
        from sqlalchemy import text as sql_text
        with app.state.session_factory() as db:
            db.execute(sql_text("SELECT 1"))
        model_ready = app.state.embedder is not None
        if not model_ready:
            raise AppError("NOT_READY", "The model is still loading.", 503,
                           headers={"Retry-After": "15"})
        return {"status": "ready", "database": "ok", "model_loaded": True}

    from backend.app.routers import auth as auth_router
    from backend.app.routers import customers as customers_router
    from backend.app.routers import verify as verify_router
    from backend.app.routers import history as history_router
    from backend.app.routers import engineering as engineering_router
    from backend.app.routers import accounts as accounts_router
    from backend.app.routers import org_admin as org_admin_router
    app.include_router(auth_router.router)
    app.include_router(customers_router.router)
    app.include_router(verify_router.router)
    app.include_router(history_router.router)
    app.include_router(engineering_router.router)
    app.include_router(accounts_router.router)
    app.include_router(org_admin_router.router)
    return app
