"""Authentication and authorization tests.

These are the highest-value tests in the suite: they prove that a request
without a verified token is rejected, and that one authenticated user cannot
read or modify another user's financial records.
"""

from __future__ import annotations

import importlib
from datetime import datetime

from app.core import config as config_module
from app.core import security as security_module
from app.tests.conftest import mint_token, resolve_user, seed_transaction, seed_user


class TestCorsGuard:
    """A credentialed API must never advertise Access-Control-Allow-Origin: *."""

    def test_wildcard_is_dropped_when_credentials_are_on(self):
        s = config_module.Settings(
            cors_origins=["*"],
            cors_allow_credentials=True,
        )
        assert s.resolved_cors_origins == []

    def test_other_origins_survive_the_wildcard_removal(self):
        s = config_module.Settings(
            cors_origins=["http://localhost:5173", "*"],
            cors_allow_credentials=True,
        )
        assert s.resolved_cors_origins == ["http://localhost:5173"]

    def test_wildcard_is_kept_when_credentials_are_off(self):
        s = config_module.Settings(
            cors_origins=["*"],
            cors_allow_credentials=False,
        )
        assert s.resolved_cors_origins == ["*"]

PROTECTED = [
    ("GET", "/api/auth/me"),
    ("GET", "/api/auth/profile"),
    ("GET", "/api/transactions"),
    ("POST", "/api/transactions"),
    ("GET", "/api/budgets"),
    ("POST", "/api/budgets"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/fraud/alerts"),
    ("GET", "/api/loans"),
    ("GET", "/api/family"),
    ("GET", "/api/notifications"),
    ("GET", "/api/backups"),
    ("GET", "/api/reports"),
    ("GET", "/api/sms/messages"),
    ("POST", "/api/sms/messages"),
    ("POST", "/api/assistant"),
    ("POST", "/api/ml/train"),
]


class TestAuthenticationRequired:
    def test_every_protected_endpoint_rejects_anonymous(self, client):
        """No endpoint may serve data without a verified token."""
        for method, path in PROTECTED:
            response = client.request(method, path, json={})
            assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
            assert "Not authenticated" in response.json()["detail"]

    def test_missing_authorization_header_is_401(self, client):
        assert client.get("/api/transactions").status_code == 401

    def test_malformed_token_is_401(self, client):
        headers = {"Authorization": "Bearer not-a-real-token"}
        response = client.get("/api/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired authentication token."

    def test_token_signed_with_wrong_secret_is_401(self, client):
        from jose import jwt

        forged = jwt.encode(
            {
                "sub": "uid-attacker",
                "email": "attacker@example.com",
                "aud": settings_app_name(),
                "exp": int((datetime.utcnow()).timestamp()) + 3600,
            },
            "a-different-secret",
            algorithm="HS256",
        )
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    def test_expired_token_is_401(self, client):
        expired = security_module.issue_dev_token(
            subject="uid-alice",
            email="alice@example.com",
            expires_minutes=-10,
        )
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {expired}"}
        )
        assert response.status_code == 401


def settings_app_name() -> str:
    return security_module.settings.app_name


class TestDevTokenEndpoint:
    def test_mints_a_usable_token(self, client):
        response = client.post(
            "/api/auth/dev-token",
            json={"subject": "uid-new", "email": "new@example.com", "name": "New"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["provider"] == "dev"

        # The minted token must actually authenticate.
        me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == "new@example.com"

    def test_config_reports_the_active_provider(self, client):
        body = client.get("/api/auth/config").json()
        assert body["provider"] == "dev"
        assert body["firebase_enabled"] is False

    def test_login_is_not_available(self, client):
        """There is no password login path any more."""
        for path in ("/api/auth/login", "/api/auth/register", "/api/auth/token"):
            assert client.post(path, json={}).status_code == 404


class TestSingleAuthPath:
    """The dev provider must become inert as soon as Firebase is configured."""

    def test_credentials_alone_disable_dev_auth(self):
        """A service-account credential is enough; the project id need not be
        exported separately. Left as-is, a deployment with credentials but no
        FIREBASE_PROJECT_ID would keep the dev provider live."""
        s = config_module.Settings(
            secret_key="test-secret-key-not-for-production",
            allow_dev_auth=True,
            app_env="test",
            firebase_project_id="",
            firebase_credentials_json='{"type":"service_account"}',
        )
        assert s.firebase_enabled is True
        assert s.dev_auth_active is False

    def test_dev_token_endpoint_disables_when_firebase_present(self, client):
        import app.routes.auth as auth_route

        firebase_settings = config_module.Settings(
            secret_key="test-secret-key-not-for-production",
            allow_dev_auth=True,
            app_env="test",
            firebase_project_id="finance-ai-test",
            firebase_credentials_json='{"type":"service_account"}',
        )
        # Every module that captured ``settings`` at import time must be
        # switched too, otherwise the route would read stale configuration.
        patched = (
            "app.core.config",
            "app.core.security",
            "app.core.deps",
            "app.routes.auth",
        )
        originals = {}
        for module_name in patched:
            module = importlib.import_module(module_name)
            originals[module_name] = getattr(module, "settings", None)
            if hasattr(module, "settings"):
                module.settings = firebase_settings
        import main

        originals["main"] = main.settings
        main.settings = firebase_settings

        try:
            body = client.get("/api/auth/config").json()
            assert body["firebase_enabled"] is True
            assert body["provider"] == "firebase"

            # The dev token endpoint must be gone entirely, not just disabled.
            assert client.post(
                "/api/auth/dev-token", json={"subject": "uid-x", "email": "x@example.com"}
            ).status_code == 404
        finally:
            for module_name, original in originals.items():
                module = importlib.import_module(module_name)
                if hasattr(module, "settings"):
                    module.settings = original


class TestUserProvisioning:
    def test_first_request_provisions_the_user(self, client):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {mint_token('uid-fresh', 'fresh@example.com', 'Fresh')}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "fresh@example.com"
        assert body["name"] == "Fresh"
        assert body["is_active"] is True

    def test_legacy_account_is_linked_by_email(self, client, db):
        """A pre-migration user keeps their data and gains a Firebase UID."""
        from app.models.user import User

        user = seed_user(db, "legacy@example.com", "Legacy Owner")
        assert user.firebase_uid is None

        response = client.get(
            "/api/auth/me",
            headers={
                "Authorization": f"Bearer {mint_token('uid-legacy', 'legacy@example.com', 'Legacy Owner')}"
            },
        )
        assert response.status_code == 200
        assert response.json()["id"] == user.id

        db.expire_all()
        refreshed = db.get(User, user.id)
        assert refreshed.firebase_uid == "uid-legacy"

    def test_unverified_email_cannot_claim_a_legacy_account(self, client, db):
        """Account-takeover guard.

        Linking a legacy row by email must require that Firebase has verified
        the address. Otherwise anyone could register the victim's email in
        Firebase (never verifying it) and be handed the victim's account.
        """
        from app.models.user import User

        victim = seed_user(db, "victim@example.com", "Victim")
        assert victim.firebase_uid is None

        token = security_module.issue_dev_token(
            subject="uid-attacker",
            email="victim@example.com",
            email_verified=False,
        )
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

        db.expire_all()
        refreshed = db.get(User, victim.id)
        # The legacy row was not claimed by the attacker.
        assert refreshed.firebase_uid is None

    def test_account_without_email_is_refused(self, client):
        """A token with no email cannot be provisioned - it has no identity key."""
        token = security_module.issue_dev_token(subject="uid-noemail", email=None)
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "no email address" in response.json()["detail"]

    def test_deactivated_account_is_refused(self, client, db):
        from app.models.user import User

        user = seed_user(db, "banned@example.com", "Banned", firebase_uid="uid-banned")
        user.is_active = False
        db.commit()

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {mint_token('uid-banned', 'banned@example.com')}"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Account is deactivated."


class TestCrossUserIsolation:
    """The IDOR regression tests.

    Each test creates a record for one user and then attempts to reach it as
    another. Every attempt must be refused.
    """

    def test_cannot_read_another_users_transaction(self, client, db, auth, other_auth):
        user_id = resolve_user(db, "uid-alice", "alice@example.com")
        victim = seed_transaction(db, user_id, merchant="Victim Merchant")

        response = client.get(f"/api/transactions/{victim.id}", headers=other_auth)
        assert response.status_code == 404
        assert response.json()["detail"] == "Transaction not found"

    def test_cannot_modify_another_users_transaction(self, client, db, auth, other_auth):
        user_id = resolve_user(db, "uid-alice", "alice@example.com")
        victim = seed_transaction(db, user_id, amount="250.00")

        response = client.patch(
            f"/api/transactions/{victim.id}",
            headers=other_auth,
            json={"amount": "1.00"},
        )
        assert response.status_code == 404

        db.expire_all()
        from app.models.transaction import Transaction

        assert float(db.get(Transaction, victim.id).amount) == 250.0

    def test_cannot_delete_another_users_transaction(self, client, db, other_auth):
        user_id = resolve_user(db, "uid-alice", "alice@example.com")
        victim = seed_transaction(db, user_id)

        assert client.delete(f"/api/transactions/{victim.id}", headers=other_auth).status_code == 404

        from app.models.transaction import Transaction

        assert db.get(Transaction, victim.id) is not None

    def test_cannot_read_another_users_budget(self, client, db, other_auth):
        from app.tests.conftest import seed_budget

        user_id = resolve_user(db, "uid-alice", "alice@example.com")
        budget = seed_budget(db, user_id)

        assert client.get(f"/api/budgets/{budget.id}", headers=other_auth).status_code == 404

    def test_cannot_delete_another_users_budget(self, client, db, other_auth):
        from app.models.budget import Budget
        from app.tests.conftest import seed_budget

        user_id = resolve_user(db, "uid-alice", "alice@example.com")
        budget = seed_budget(db, user_id)

        assert client.delete(f"/api/budgets/{budget.id}", headers=other_auth).status_code == 404
        assert db.get(Budget, budget.id) is not None

    def test_lists_only_contain_the_callers_own_rows(self, client, db, auth, other_auth):
        mine_id = resolve_user(db, "uid-alice", "alice@example.com")
        theirs_id = resolve_user(db, "uid-bob", "bob@example.com")
        seed_transaction(db, mine_id, merchant="Alice Coffee")
        seed_transaction(db, theirs_id, merchant="Bob Secret Purchase")

        alice_sees = client.get("/api/transactions", headers=auth).json()
        merchants = {t["merchant"] for t in alice_sees["items"]}
        assert "Alice Coffee" in merchants
        assert "Bob Secret Purchase" not in merchants

        bob_sees = client.get("/api/transactions", headers=other_auth).json()
        bob_merchants = {t["merchant"] for t in bob_sees["items"]}
        assert "Bob Secret Purchase" in bob_merchants
        assert "Alice Coffee" not in bob_merchants

    def test_dashboard_totals_are_per_user(self, client, db, auth, other_auth):
        from decimal import Decimal

        mine_id = resolve_user(db, "uid-alice", "alice@example.com")
        theirs_id = resolve_user(db, "uid-bob", "bob@example.com")
        seed_transaction(db, mine_id, amount=Decimal("100.00"))
        seed_transaction(db, theirs_id, amount=Decimal("9999.00"))

        alice_total = float(client.get("/api/dashboard/summary", headers=auth).json()["expense"])
        bob_total = float(client.get("/api/dashboard/summary", headers=other_auth).json()["expense"])

        assert alice_total < bob_total
        assert alice_total < 1000

    def test_created_transaction_is_owned_by_the_caller(self, client, auth):
        response = client.post(
            "/api/transactions",
            headers=auth,
            json={
                "transaction_type": "expense",
                "amount": "42.50",
                "category": "Food",
                "transaction_date": "2026-01-15T10:00:00",
            },
        )
        assert response.status_code == 201
        body = response.json()
        me = client.get("/api/auth/me", headers=auth).json()
        assert body["user_id"] == me["id"]

    def test_client_supplied_user_id_is_ignored(self, client, auth):
        """A ``user_id`` in the body must not become the owner."""
        response = client.post(
            "/api/transactions",
            headers=auth,
            json={
                "transaction_type": "expense",
                "amount": "15.00",
                "category": "Food",
                "transaction_date": "2026-01-15T10:00:00",
                "user_id": 999999,
            },
        )
        assert response.status_code == 201
        me = client.get("/api/auth/me", headers=auth).json()
        assert response.json()["user_id"] == me["id"]
        assert response.json()["user_id"] != 999999

    def test_family_group_requires_membership(self, client, db, auth, other_auth):
        created = client.post(
            "/api/family", headers=auth, json={"name": "Alice household"}
        )
        assert created.status_code == 201
        group_id = created.json()["id"]

        assert client.get(f"/api/family/{group_id}", headers=other_auth).status_code == 404
        assert client.get(f"/api/family/{group_id}/members", headers=other_auth).status_code == 404
        assert (
            client.post(
                f"/api/family/{group_id}/members",
                headers=other_auth,
                json={"email": "intuder@example.com"},
            ).status_code
            == 404
        )

    def test_loan_is_not_reachable_by_another_user(self, client, db, auth, other_auth):
        created = client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Alice car loan",
                "principal": "500000.00",
                "interest_rate": "8.5",
                "tenure_months": 60,
                "start_date": "2026-01-01",
            },
        )
        assert created.status_code == 201
        loan_id = created.json()["id"]

        assert client.get(f"/api/loans/{loan_id}", headers=other_auth).status_code == 404
        assert client.delete(f"/api/loans/{loan_id}", headers=other_auth).status_code == 404

    def test_fraud_alert_of_another_user_is_hidden(self, client, db, other_auth):
        from app.models.fraud_alert import DetectionLayer, FraudAlert, RiskLevel
        from app.models.user import User

        owner = db.execute(
            User.__table__.select().where(User.email == "alice@example.com")
        ).first()
        user_id = owner[0] if owner else resolve_user(db, "uid-alice", "alice@example.com")
        alert = FraudAlert(
            user_id=user_id,
            risk_score=90,
            risk_level=RiskLevel.HIGH,
            is_fraud=True,
            detection_layer=DetectionLayer.RULES,
            reasons=["test"],
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        assert client.get(f"/api/fraud/alerts/{alert.id}", headers=other_auth).status_code == 404
        listing = client.get("/api/fraud/alerts", headers=other_auth).json()
        assert alert.id not in {a["id"] for a in listing["items"]}

