"""Database engine, session factory and declarative base."""

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


DATABASE_URL = build_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=settings.db_echo,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()