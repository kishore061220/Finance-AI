"""Finance-AI API entry point.

Schema changes are managed by Alembic. ``Base.metadata.create_all()`` has been
removed on purpose: it silently creates tables that the migration history does
not know about and it cannot alter an existing table, so it would let a
deployment drift away from the schema. Run ``alembic upgrade head`` instead.

Startup does not run migrations either. Applying schema changes is an explicit
operator action, so a deploy can never mutate the database as a side effect of
starting the process.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.database.connection import get_engine


class _LazyEngine:
    """Resolves to the real engine on first use.

    Importing this module must not require database credentials, so the engine is
    not built here. Attribute access is forwarded unchanged, which keeps
    ``main.engine`` working exactly as before - including for tests that
    substitute a failing engine to assert that ``/health`` degrades without
    leaking the connection string.
    """

    def __getattr__(self, name):
        return getattr(get_engine(), name)


engine = _LazyEngine()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("finance_ai")

# Importing the model package registers every table on ``Base.metadata`` so
# Alembic autogenerate and the health check see the full schema.
import app.models  # noqa: F401,E402  (import for side effect)

from app.routes.assistant import router as assistant_router  # noqa: E402
from app.routes.auth import router as auth_router  # noqa: E402
from app.routes.backups import router as backup_router  # noqa: E402
from app.routes.budgets import router as budget_router  # noqa: E402
from app.routes.categorization import router as categorization_router  # noqa: E402
from app.routes.dashboard import router as dashboard_router  # noqa: E402
from app.routes.family import router as family_router  # noqa: E402
from app.routes.fraud import router as fraud_router  # noqa: E402
from app.routes.loans import router as loan_router  # noqa: E402
from app.routes.ml import router as ml_router  # noqa: E402
from app.routes.notifications import router as notification_router  # noqa: E402
from app.routes.reports import router as report_router  # noqa: E402
from app.routes.transactions import router as transaction_router  # noqa: E402

VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Verify connectivity and configuration, then serve.

    Failures here are logged and reported through ``/health`` rather than
    raised, so a database hiccup does not make the service unlistable - except
    for a misconfigured production, which must not serve traffic at all.
    """
    if settings.is_production and not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY must be set when APP_ENV is production. Refusing to start."
        )

    if settings.is_production and settings.allow_dev_auth:
        raise RuntimeError(
            "ALLOW_DEV_AUTH must be false in production. Refusing to start."
        )

    if not settings.firebase_enabled:
        logger.warning(
            "Firebase is NOT configured. Every protected endpoint will reject "
            "real requests. Set FIREBASE_PROJECT_ID and credentials before "
            "serving users."
        )
    if not settings.dev_auth_active and not settings.firebase_enabled:
        logger.error(
            "No authentication provider is active. All protected endpoints "
            "will return 401. Configure Firebase, or set ALLOW_DEV_AUTH=true "
            "with a SECRET_KEY for local development only."
        )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database connection OK (%s)", settings.db_name)
    except Exception as exc:  # noqa: BLE001
        logger.error("Database connection FAILED: %s", exc)

    logger.info("Finance-AI API %s ready (env=%s)", VERSION, settings.app_env)
    yield
    engine.dispose()
    logger.info("Finance-AI API shut down cleanly")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Personal finance management with fraud detection, family expense "
        "sharing, loan tracking, backup and reporting. "
        "Authenticate with a Firebase ID token as `Authorization: Bearer <token>`."
    ),
    version=VERSION,
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    # A wildcard origin is unsafe once credentialed requests are allowed, so
    # the configured list is authoritative. With no list configured and
    # credentials off, the API is not browser-reachable by design.
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["Content-Disposition", "X-Report-Id", "X-Row-Count"],
)

for router in (
    auth_router,
    transaction_router,
    budget_router,
    dashboard_router,
    fraud_router,
    categorization_router,
    loan_router,
    family_router,
    notification_router,
    backup_router,
    report_router,
    assistant_router,
    ml_router,
):
    app.include_router(router)


@app.get("/", tags=["meta"])
def root():
    return {
        "message": f"{settings.app_name} is running",
        "version": VERSION,
        "auth_provider": (
            "firebase" if settings.firebase_enabled
            else "dev" if settings.dev_auth_active
            else "unconfigured"
        ),
        "docs": "/docs" if not settings.is_production else None,
    }


@app.get("/health", tags=["meta"])
def health_check():
    """Liveness plus a real database round trip.

    Returns 503 when the database is unreachable so a load balancer can act on
    it instead of routing traffic to a broken instance.

    This endpoint is unauthenticated, so it deliberately reports *whether* the
    configuration is complete but never the configuration itself: no database
    name, no DSN, no exception text (a SQLAlchemy error can echo the host, port
    and credentials it was built from), and no secret values.
    """
    db_ok = True
    db_error_type = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        # Class name only - never str(exc), which can leak the DSN.
        db_error_type = type(exc).__name__

    payload = {
        "status": "healthy" if db_ok else "degraded",
        "service": "finance-ai-api",
        "version": VERSION,
        "database": {"connected": db_ok},
        "auth": {
            "firebase_enabled": settings.firebase_enabled,
            "dev_auth_active": settings.dev_auth_active,
        },
    }
    if db_error_type:
        payload["database"]["error_type"] = db_error_type
    return JSONResponse(
        status_code=200 if db_ok else 503, content=payload
    )


@app.get("/api/info", tags=["meta"])
def api_info():
    """Static API surface, useful for the client's feature detection."""
    return {
        "name": settings.app_name,
        "version": VERSION,
        "features": {
            "transactions": True,
            "budgets": True,
            "dashboard_analytics": True,
            "fraud_detection": True,
            "fraud_ml": True,
            "sms_parsing": True,
            "ocr_parsing": True,
            "loans": True,
            "family_sharing": True,
            "notifications_push": True,
            "cloud_backup": True,
            "reports": True,
            "assistant": True,
        },
        "formats": {"reports": ["CSV", "EXCEL", "PDF"]},
    }
