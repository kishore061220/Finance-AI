"""Database engine, session factory and declarative base.

The engine is built lazily. Importing this module must not require database
credentials: the test suite substitutes its own engine and never reaches the
configured one, so requiring ``DB_USER``/``DB_PASSWORD`` at import time made
``pytest`` fail outright on any machine without a ``.env`` file - including a CI
runner, which by design has none.
"""

from __future__ import annotations

from typing import Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def build_database_url() -> str:
    """Assemble the MySQL connection URL.

    The password is URL-encoded because the configured credential contains
    reserved characters (``@``, ``+``, ``-``, ``*``) which would otherwise
    corrupt the URL.
    """
    if not settings.db_user:
        raise RuntimeError("DB_USER is not configured in the environment")
    if not settings.db_password:
        raise RuntimeError("DB_PASSWORD is not configured in the environment")

    return (
        f"mysql+pymysql://{settings.db_user}:{quote_plus(settings.db_password)}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


_engine = None
_session_factory = None
_database_url = None


def get_database_url() -> str:
    """The configured MySQL URL, assembled once."""
    global _database_url
    if _database_url is None:
        _database_url = build_database_url()
    return _database_url


def get_engine():
    """The application engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=settings.db_echo,
            future=True,
        )
    return _engine


def get_session_factory():
    """The application session factory, created on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _session_factory


def __getattr__(name: str):
    """Expose ``engine``/``SessionLocal``/``DATABASE_URL`` lazily (PEP 562).

    Every existing ``from app.database.connection import engine`` keeps working;
    the credential check simply happens on first use instead of on import.
    """
    if name == "DATABASE_URL":
        return get_database_url()
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":

        def SessionLocal(*args, **kwargs):  # noqa: N802 - mirrors sessionmaker
            return get_session_factory()(*args, **kwargs)

        return SessionLocal
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    db = get_session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()