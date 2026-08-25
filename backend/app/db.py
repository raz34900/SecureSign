from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str, **kwargs) -> Engine:
    # A bare postgresql:// URL selects psycopg2, which this project does not install, and
    # the failure is a ModuleNotFoundError at engine construction - so the API crash-loops
    # at boot rather than saying which driver it wanted. Name the driver we ship.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql"):
        # A pooled connection whose socket died quietly - an idle timeout on a firewall
        # between machines, a database restart - is otherwise handed out as-is, and the
        # first request after the outage pays for it. The ping costs one round trip per
        # checkout and makes recovery invisible instead of one-error-then-fine.
        kwargs.setdefault("pool_pre_ping", True)
        # Bounded, so a hung database refuses in seconds instead of pinning a worker for
        # as long as the kernel will wait. Nothing this application runs takes 30s.
        kwargs.setdefault("connect_args", {
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000",
        })
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
