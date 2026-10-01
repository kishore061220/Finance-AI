"""Shared test fixtures.

The API is exercised against an in-memory SQLite database with the real
dependency chain intact: routes run, ``get_current_user`` resolves the identity
from a *signed* dev token, and ownership is enforced by the real query
filters. Only the database engine is substituted, so these tests verify the
authorization logic rather than a mock of it.

The dev provider is active here only because these tests explicitly configure
it. ``test_auth_is_single_path`` asserts that it switches off the moment
Firebase is configured.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

# The dev token provider must be active before any app module is imported,
# because ``settings`` is frozen at import time and the verifier is cached.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ALLOW_DEV_AUTH", "true")
os.environ.setdefault("DB_ECHO", "false")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (register every table)
from app.core import config as config_module  # noqa: E402
from app.core import security as security_module  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.deps import get_db  # noqa: E402
from app.database.connection import Base  # noqa: E402

# Force the dev provider by clearing any Firebase configuration that a
# developer's real .env may have left in the environment.
settings = config_module.Settings(
    secret_key="test-secret-key-not-for-production",
    allow_dev_auth=True,
    app_env="test",
    firebase_project_id="",
    firebase_credentials_json="",
)
security_module.settings = settings
security_module.reset_token_verifier()

for _module_name in ("app.core.config", "app.core.security", "app.core.deps"):
    _module = importlib.import_module(_module_name)
    if hasattr(_module, "settings"):
        _module.settings = settings


@pytest.fixture(scope="session")
def engine():
    """One in-memory database shared by the whole session."""
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db(session_factory):
    """A session for direct database setup inside a test.

    Route handlers call ``commit()``, so an outer wrapping transaction would be
    closed out from under the fixture. Tables are therefore cleared between
    tests by :func:`_clean_database` instead of rolled back.
    """
    connection = session_factory()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _isolate(session_factory, tmp_path_factory):
    """Give every test an empty database and a private backup directory."""
    _clean_database(session_factory)

    # The LOCAL backup provider writes to ``finance-ai-api/backups``. Without
    # this, any test that creates a backup litters the working tree with real
    # files, and a later test can read a previous test's backup. Redirecting it
    # here means no test can touch the project directory by accident.
    from app.services import backup as backup_module

    original_dir = backup_module.LOCAL_BACKUP_DIR
    backup_module.LOCAL_BACKUP_DIR = tmp_path_factory.mktemp("backups") / "local"
    try:
        yield
    finally:
        backup_module.LOCAL_BACKUP_DIR = original_dir
        _clean_database(session_factory)


def _clean_database(session_factory) -> None:
    connection = session_factory()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
        connection.commit()
    finally:
        connection.close()


@pytest.fixture()
def client(engine, session_factory):
    """TestClient wired to the in-memory database."""
    import main as main_module

    main_module.settings = settings

    def override_get_db():
        connection = session_factory()
        try:
            yield connection
        finally:
            connection.close()

    main_module.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main_module.app, raise_server_exceptions=False) as test_client:
        yield test_client
    main_module.app.dependency_overrides.clear()


def mint_token(subject: str, email: str, name: str = "Test User") -> str:
    """Sign a dev token exactly as the /api/auth/dev-token endpoint would."""
    return security_module.issue_dev_token(
        subject=subject, email=email, display_name=name
    )


@pytest.fixture()
def token():
    return mint_token("uid-alice", "alice@example.com", "Alice")


@pytest.fixture()
def other_token():
    return mint_token("uid-bob", "bob@example.com", "Bob")


@pytest.fixture()
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def other_auth(other_token):
    return {"Authorization": f"Bearer {other_token}"}


def seed_user(db, email: str, name: str = "Test User", firebase_uid: str | None = None):
    from app.models.user import User

    user = User(
        email=email,
        name=name,
        firebase_uid=firebase_uid,
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_transaction(db, user_id: int, **overrides):
    from app.models.transaction import Transaction, TransactionType

    payload = {
        "user_id": user_id,
        "transaction_type": TransactionType.EXPENSE,
        "amount": Decimal("100.00"),
        "category": "Food",
        "transaction_date": datetime.utcnow().replace(microsecond=0),
    }
    payload.update(overrides)
    transaction = Transaction(**payload)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def seed_budget(db, user_id: int, **overrides):
    from app.models.budget import Budget

    now = datetime.utcnow()
    payload = {
        "user_id": user_id,
        "category": "Food",
        "amount": Decimal("500.00"),
        "month": now.month,
        "year": now.year,
    }
    payload.update(overrides)
    budget = Budget(**payload)
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def resolve_user(db, firebase_uid: str, email: str) -> int:
    """Return the local user id for an identity, provisioning it if absent.

    Mirrors what ``get_current_user`` does on a real request, so a test can
    create data "belonging to" a user before that user has made a request.
    """
    from app.models.user import User

    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if user is not None:
        return user.id

    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        user.firebase_uid = firebase_uid
        db.commit()
        return user.id

    user = User(
        firebase_uid=firebase_uid,
        email=email,
        name=email.split("@")[0],
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id
