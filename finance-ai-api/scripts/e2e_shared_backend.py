"""End-to-end proof that the Web and Mobile clients share one backend + database.

This script runs OUTSIDE pytest on purpose. The unit suite substitutes an
in-memory SQLite engine, which is the right thing for fast, isolated tests but
cannot prove anything about the real MySQL schema or about two clients seeing
the same rows. So this script:

  1. refuses to run unless the target database is the dedicated ``finance_ai_e2e``
     database (never the live ``finance_ai`` one),
  2. creates that database and applies every Alembic migration to it,
  3. starts the real FastAPI app against it,
  4. drives it through two independent HTTP sessions that stand in for the two
     clients - a "web" session and a "mobile" session for the same user - plus a
     third session for a different user,
  5. asserts cross-client visibility, persistence across a re-login, and
     per-user isolation, then reads a row straight from MySQL to confirm it
     landed in the shared database.

No Firebase credentials are required: the dev token provider mints the bearer
tokens, exactly as the API unit tests do. This exercises the shared *backend and
database*, not the (separately blocked) real-Firebase sign-in path.

Run with the backend virtualenv, from the backend directory::

    $env:DB_NAME = "finance_ai_e2e"
    $env:ALLOW_DEV_AUTH = "true"
    .\\.venv\\Scripts\\python.exe scripts\\e2e_shared_backend.py

Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Hard configuration guards, applied before any app import ---------------
# The database name is what keeps this script from ever touching live data. It
# is set here, not inherited, so a stale shell variable cannot retarget it.
TARGET_DB = "finance_ai_e2e"
LIVE_DB = "finance_ai"

if TARGET_DB == LIVE_DB or not TARGET_DB.endswith("_e2e"):
    raise SystemExit("Refusing to run: target database is not a dedicated e2e database.")

os.environ["DB_NAME"] = TARGET_DB
os.environ["ALLOW_DEV_AUTH"] = "true"
# The dev provider is only skipped when Firebase is configured. Ensure this
# script cannot silently use Firebase even if the developer's shell exported it.
for _name in (
    "FIREBASE_PROJECT_ID",
    "FIREBASE_CREDENTIALS_PATH",
    "FIREBASE_CREDENTIALS_JSON",
    "GOOGLE_APPLICATION_CREDENTIALS",
):
    os.environ.pop(_name, None)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pymysql  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.database.connection import Base, get_session_factory  # noqa: E402
from app.models.transaction import Transaction  # noqa: E402
from app.models.user import User  # noqa: E402
from main import app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" - {detail}"
    print(line, flush=True)


def guard_configuration() -> None:
    if settings.db_name != TARGET_DB:
        raise SystemExit(
            f"Refusing to run: settings.db_name is {settings.db_name!r}, expected {TARGET_DB!r}."
        )
    if settings.firebase_enabled:
        raise SystemExit("Refusing to run: Firebase is configured; this is a dev-auth E2E.")
    if not settings.dev_auth_active:
        raise SystemExit(
            "Dev auth is not active (need ALLOW_DEV_AUTH=true and a SECRET_KEY in .env)."
        )
    check("guard: target database is dedicated and not the live database", True, TARGET_DB)


def create_database() -> None:
    """Create the e2e database if it does not exist, connecting as configured."""
    connection = pymysql.connect(
        host=settings.db_host,
        port=int(settings.db_port),
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{TARGET_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        connection.commit()
    finally:
        connection.close()
    check("database: dedicated database exists", True, TARGET_DB)


def migrate() -> None:
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")
    check("database: alembic upgrade head applied", True)


def truncate_all() -> None:
    """Start from a clean slate. Only ever the e2e database (guarded above)."""
    session = get_session_factory()()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()


def dev_token(client: TestClient, subject: str, email: str, name: str) -> None:
    response = client.post(
        "/api/auth/dev-token",
        json={"subject": subject, "email": email, "name": name},
    )
    if response.status_code != 200:
        raise SystemExit(f"dev-token failed ({response.status_code}): {response.text}")
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def main() -> int:
    guard_configuration()
    create_database()
    migrate()
    truncate_all()

    web = TestClient(app)
    mobile = TestClient(app)
    other = TestClient(app)
    with web, mobile, other:
        dev_token(web, "e2e-web-user", "web@example.com", "Web User")
        dev_token(mobile, "e2e-web-user", "web@example.com", "Web User")
        dev_token(other, "e2e-other-user", "other@example.com", "Other User")

        # --- Identity: two clients, one user in one database ------------------
        web_me = web.get("/api/auth/me")
        mobile_me = mobile.get("/api/auth/me")
        web_id = web_me.json().get("id") if web_me.status_code == 200 else None
        mobile_id = mobile_me.json().get("id") if mobile_me.status_code == 200 else None
        check(
            "identity: web and mobile sessions resolve to the same user",
            web_id is not None and web_id == mobile_id,
            f"web={web_id} mobile={mobile_id}",
        )

        # --- Cross-client visibility: web writes, mobile reads ----------------
        created = web.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": "123.45",
                "category": "Groceries",
                "merchant": "E2E Market",
                "transaction_date": datetime.now(timezone.utc).isoformat(),
            },
        )
        check(
            "write: web client created a transaction",
            created.status_code == 201,
            f"status={created.status_code}",
        )
        tx_id = created.json().get("id") if created.status_code == 201 else None

        mobile_list = mobile.get("/api/transactions", params={"page_size": 50})
        mobile_items = mobile_list.json().get("items", []) if mobile_list.status_code == 200 else []
        check(
            "shared visibility: mobile client sees the web client's transaction",
            any(item.get("id") == tx_id for item in mobile_items),
            f"tx_id={tx_id} mobile_count={len(mobile_items)}",
        )

        # --- Reverse direction: mobile writes, web reads ----------------------
        now = datetime.now(timezone.utc)
        budget = mobile.post(
            "/api/budgets",
            json={
                "category": "Groceries",
                "amount": "500.00",
                "month": now.month,
                "year": now.year,
            },
        )
        check("write: mobile client created a budget", budget.status_code == 201,
              f"status={budget.status_code}")
        web_budgets = web.get(
            "/api/budgets", params={"month": now.month, "year": now.year}
        )
        web_budget_items = (
            web_budgets.json().get("items", []) if web_budgets.status_code == 200 else []
        )
        check(
            "shared visibility: web client sees the mobile client's budget",
            any(item.get("category") == "Groceries" for item in web_budget_items),
            f"web_budget_count={len(web_budget_items)}",
        )

        # --- Persistence across a re-login ------------------------------------
        # A re-login is a new token for the same subject. The row must survive
        # because it lives in MySQL, not in either client's memory.
        dev_token(web, "e2e-web-user", "web@example.com", "Web User")
        after_login = web.get("/api/transactions", params={"page_size": 50})
        after_items = after_login.json().get("items", []) if after_login.status_code == 200 else []
        check(
            "persistence: transaction survives web re-login",
            any(item.get("id") == tx_id for item in after_items),
            f"tx_id={tx_id}",
        )

        # --- Isolation: the other user sees none of it ------------------------
        other_tx = other.get("/api/transactions", params={"page_size": 50})
        other_tx_items = other_tx.json().get("items", []) if other_tx.status_code == 200 else []
        other_budgets = other.get(
            "/api/budgets", params={"month": now.month, "year": now.year}
        )
        other_budget_items = (
            other_budgets.json().get("items", []) if other_budgets.status_code == 200 else []
        )
        check(
            "isolation: another user cannot see the transaction",
            all(item.get("id") != tx_id for item in other_tx_items),
            f"other_tx_count={len(other_tx_items)}",
        )
        check(
            "isolation: another user cannot see the budget",
            all(item.get("category") != "Groceries" for item in other_budget_items),
            f"other_budget_count={len(other_budget_items)}",
        )

        # --- Database-level confirmation --------------------------------------
        session = get_session_factory()()
        try:
            row = session.execute(
                select(Transaction).where(Transaction.id == tx_id)
            ).scalar_one_or_none()
            owner = None
            if row is not None:
                user = session.execute(
                    select(User).where(User.id == row.user_id)
                ).scalar_one_or_none()
                owner = user.email if user else None
            check(
                "database: transaction row exists in the shared MySQL database",
                row is not None and row.amount is not None and owner == "web@example.com",
                f"owner={owner}",
            )
        finally:
            session.close()

        # --- T7 feature endpoints, over the shared backend --------------------
        report_types = web.get("/api/reports/types")
        types_body = report_types.json() if report_types.status_code == 200 else {}
        check(
            "reports: types endpoint lists TRANSACTIONS",
            "TRANSACTIONS" in types_body.get("report_types", []),
            f"types={types_body.get('report_types')}",
        )
        generated = web.post(
            "/api/reports/generate",
            json={"report_type": "TRANSACTIONS", "report_format": "CSV"},
        )
        check(
            "reports: generate streams a file",
            generated.status_code == 200,
            f"status={generated.status_code} content_type={generated.headers.get('content-type')}",
        )
        history = web.get("/api/reports")
        history_body = history.json() if history.status_code == 200 else []
        check(
            "reports: generation recorded in history",
            any(item.get("report_type") == "TRANSACTIONS" for item in history_body),
            f"history_count={len(history_body)}",
        )

        assistant_config = web.get("/api/assistant/config")
        config_body = assistant_config.json() if assistant_config.status_code == 200 else {}
        check(
            "assistant: config reports an active provider",
            bool(config_body.get("provider")),
            f"provider={config_body.get('provider')}",
        )
        answer = web.post("/api/assistant", json={"message": "How much did I spend?"})
        answer_body = answer.json() if answer.status_code == 200 else {}
        check(
            "assistant: ask returns a reply",
            bool(answer_body.get("reply")) and "fallback" in answer_body,
            f"provider={answer_body.get('provider')} fallback={answer_body.get('fallback')}",
        )

        group = web.post("/api/family", json={"name": "E2E Household"})
        check("family: group created", group.status_code == 201, f"status={group.status_code}")
        group_id = group.json().get("id") if group.status_code == 201 else None
        invite = web.post(
            f"/api/family/{group_id}/members",
            json={"email": "member@example.com", "can_view_all": True},
        )
        check(
            "family: member invited",
            invite.status_code == 201,
            f"status={invite.status_code}",
        )
        members = web.get(f"/api/family/{group_id}/members")
        member_body = members.json() if members.status_code == 200 else []
        check(
            "family: member list shows owner and invite",
            len(member_body) >= 2,
            f"member_count={len(member_body)}",
        )

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\nE2E shared-backend: {passed}/{total} checks passed", flush=True)
    failures = [name for name, ok, _ in RESULTS if not ok]
    if failures:
        print("FAILURES:", flush=True)
        for name in failures:
            print(f"  - {name}", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
