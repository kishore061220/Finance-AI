"""Feature endpoint tests.

Covers the transaction/budget/dashboard/fraud/loan/family/notification/backup/
report/assistant/ML surface, including the "be honest when a provider is not
configured" behaviour that the cloud integrations are required to have.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.tests.conftest import resolve_user, seed_budget, seed_transaction


def tx_payload(**overrides):
    payload = {
        "transaction_type": "expense",
        "amount": "250.00",
        "category": "Food",
        "merchant": "Corner Cafe",
        "transaction_date": datetime.utcnow().replace(microsecond=0).isoformat(),
    }
    payload.update(overrides)
    return payload


class _FailingEngine:
    """Stand-in for ``engine`` whose connect() always raises.

    Lets a test drive the health check's failure branch without touching the
    real database.
    """

    def __init__(self, raiser):
        self._raiser = raiser

    def connect(self):
        raise self._raiser()


class TestTransactionCrud:
    def test_create_and_read_back(self, client, auth):
        created = client.post("/api/transactions", headers=auth, json=tx_payload())
        assert created.status_code == 201
        assert created.json()["amount"] == "250.00"
        assert created.json()["category"] == "Food"

        fetched = client.get(
            f"/api/transactions/{created.json()['id']}", headers=auth
        )
        assert fetched.status_code == 200
        assert fetched.json()["id"] == created.json()["id"]

    def test_update(self, client, auth):
        created = client.post("/api/transactions", headers=auth, json=tx_payload())
        updated = client.patch(
            f"/api/transactions/{created.json()['id']}",
            headers=auth,
            json={"amount": "300.75", "category": "Dining"},
        )
        assert updated.status_code == 200
        assert updated.json()["amount"] == "300.75"
        assert updated.json()["category"] == "Dining"

    def test_delete(self, client, auth):
        created = client.post("/api/transactions", headers=auth, json=tx_payload())
        tid = created.json()["id"]
        assert client.delete(f"/api/transactions/{tid}", headers=auth).status_code == 204
        assert client.get(f"/api/transactions/{tid}", headers=auth).status_code == 404

    def test_rejects_negative_amount(self, client, auth):
        response = client.post(
            "/api/transactions", headers=auth, json=tx_payload(amount="-5.00")
        )
        assert response.status_code == 422

    def test_rejects_unknown_transaction_type(self, client, auth):
        response = client.post(
            "/api/transactions", headers=auth, json=tx_payload(transaction_type="transfer")
        )
        assert response.status_code == 422

    def test_filters(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        seed_transaction(db, uid, category="Food", amount=Decimal("10.00"))
        seed_transaction(db, uid, category="Rent", amount=Decimal("1000.00"))

        food = client.get("/api/transactions?category=Food", headers=auth).json()
        assert food["total"] == 1
        assert food["items"][0]["category"] == "Food"

        expensive = client.get("/api/transactions?min_amount=500", headers=auth).json()
        assert expensive["total"] == 1
        assert expensive["items"][0]["category"] == "Rent"

    def test_invalid_sort_is_rejected(self, client, auth):
        response = client.get("/api/transactions?sort=amount_asc; DROP TABLE", headers=auth)
        assert response.status_code == 422

    def test_bulk_import_skips_duplicate_references(self, client, auth):
        payload = {
            "transactions": [
                {**tx_payload(), "bank_reference": "REF-1", "amount": "10.00"},
                {**tx_payload(), "bank_reference": "REF-1", "amount": "10.00"},
                {**tx_payload(), "bank_reference": "REF-2", "amount": "20.00"},
            ]
        }
        first = client.post("/api/transactions/bulk", headers=auth, json=payload).json()
        assert first["created"] == 2
        assert first["skipped"] == 1

        second = client.post("/api/transactions/bulk", headers=auth, json=payload).json()
        assert second["created"] == 0
        assert second["skipped"] == 3

    def test_bulk_import_dry_run_writes_nothing(self, client, auth):
        payload = {"transactions": [tx_payload()], "dry_run": True}
        result = client.post("/api/transactions/bulk", headers=auth, json=payload).json()
        assert result["created"] == 1
        assert client.get("/api/transactions", headers=auth).json()["total"] == 0

    def test_recent_endpoint(self, client, auth):
        client.post("/api/transactions", headers=auth, json=tx_payload())
        recent = client.get("/api/transactions/recent?limit=5", headers=auth).json()
        assert len(recent["items"]) == 1


class TestBudgets:
    def test_create_and_list_with_progress(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        now = datetime.utcnow()
        seed_transaction(db, uid, category="Food", amount=Decimal("250.00"))

        created = client.post(
            "/api/budgets",
            headers=auth,
            json={
                "category": "Food",
                "amount": "500.00",
                "month": now.month,
                "year": now.year,
            },
        )
        assert created.status_code == 201

        listing = client.get("/api/budgets", headers=auth).json()
        assert listing["total"] == 1
        progress = listing["items"][0]
        assert progress["spent"] == "250.00"
        assert progress["limit"] == "500.00"
        assert progress["used_percent"] == 50.0
        assert progress["status"] == "OK"

    def test_duplicate_budget_is_rejected(self, client, auth):
        now = datetime.utcnow()
        payload = {
            "category": "Food",
            "amount": "500.00",
            "month": now.month,
            "year": now.year,
        }
        assert client.post("/api/budgets", headers=auth, json=payload).status_code == 201
        second = client.post("/api/budgets", headers=auth, json=payload)
        assert second.status_code == 409

    def test_over_budget_is_flagged(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        now = datetime.utcnow()
        seed_transaction(db, uid, category="Rent", amount=Decimal("1200.00"))
        client.post(
            "/api/budgets",
            headers=auth,
            json={"category": "Rent", "amount": "1000.00", "month": now.month, "year": now.year},
        )
        listing = client.get("/api/budgets", headers=auth).json()
        assert listing["items"][0]["status"] == "OVER"

    def test_period_endpoint_validates_month(self, client, auth):
        assert client.get("/api/budgets/period/2026/13", headers=auth).status_code == 422
        assert client.get("/api/budgets/period/2026/1", headers=auth).status_code == 200


class TestDashboard:
    def test_totals_and_breakdown(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        now = datetime.utcnow()
        from app.models.transaction import TransactionType

        seed_transaction(
            db, uid, category="Food", amount=Decimal("300.00"),
            transaction_date=now, transaction_type=TransactionType.EXPENSE,
        )
        seed_transaction(
            db, uid, category="Salary", amount=Decimal("1000.00"),
            transaction_date=now, transaction_type=TransactionType.INCOME,
        )

        summary = client.get("/api/dashboard/summary", headers=auth).json()
        assert summary["expense"] == "300.00"
        assert summary["income"] == "1000.00"
        assert summary["net"] == "700.00"
        assert summary["savings_rate_percent"] == 70.0

        breakdown = client.get("/api/dashboard/categories", headers=auth).json()
        assert breakdown[0]["category"] == "Food"
        assert breakdown[0]["percent"] == 100.0

    def test_full_dashboard_shape(self, client, auth):
        body = client.get("/api/dashboard", headers=auth).json()
        for key in (
            "totals", "category_breakdown", "top_merchants", "budget_progress",
            "monthly_trend", "insights", "fraud_summary", "recurring", "generated_at",
        ):
            assert key in body, f"dashboard is missing '{key}'"

    def test_health_endpoint(self, client, auth):
        body = client.get("/api/dashboard/health", headers=auth).json()
        assert "transaction_count" in body
        assert body["spending_insights_available"] is False


class TestFraud:
    def test_large_amount_at_night_is_flagged(self, client, auth):
        created = client.post(
            "/api/transactions",
            headers=auth,
            json=tx_payload(amount="250000.00", transaction_date="2026-01-15T02:30:00"),
        )
        assert created.status_code == 201
        assert created.json()["is_flagged"] is True
        assert created.json()["fraud_score"] >= 30

        alerts = client.get("/api/fraud/alerts", headers=auth).json()
        assert alerts["total"] == 1
        assert alerts["items"][0]["reasons"]

    def test_ordinary_transaction_is_not_flagged(self, client, auth):
        created = client.post(
            "/api/transactions",
            headers=auth,
            json=tx_payload(amount="12.50", transaction_date="2026-01-15T13:00:00"),
        )
        assert created.json()["is_flagged"] is False
        assert client.get("/api/fraud/alerts", headers=auth).json()["total"] == 0

    def test_dismiss_alert(self, client, auth):
        client.post(
            "/api/transactions",
            headers=auth,
            json=tx_payload(amount="250000.00", transaction_date="2026-01-15T02:30:00"),
        )
        alert_id = client.get("/api/fraud/alerts", headers=auth).json()["items"][0]["id"]
        dismissed = client.post(
            f"/api/fraud/alerts/{alert_id}/dismiss", headers=auth
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["is_dismissed"] is True
        assert client.get("/api/fraud/alerts", headers=auth).json()["total"] == 0

    def test_dry_run_score_does_not_persist(self, client, auth):
        response = client.post(
            "/api/ml/score?amount=250000&transaction_date=2026-01-15T02:30:00",
            headers=auth,
        )
        assert response.status_code == 200
        assert response.json()["combined_score"] is not None
        assert client.get("/api/transactions", headers=auth).json()["total"] == 0

    def test_ml_status_is_honest_about_no_model(self, client, auth):
        body = client.get("/api/ml/status", headers=auth).json()
        assert "scoring_mode" in body
        if body["model_loaded"] is False:
            assert body["scoring_mode"] == "rules_only"
            assert body["metrics"] is None if "metrics" in body else True

    def test_training_without_enough_data_reports_it(self, client, auth):
        response = client.post("/api/ml/train?min_samples=50", headers=auth)
        # Either forbidden (not OWNER) or an explicit insufficient_data payload.
        assert response.status_code in (403, 422)
        if response.status_code == 422:
            assert response.json()["detail"]["status"] == "insufficient_data"

    def test_train_rejects_lowering_the_threshold_below_the_floor(self, client, db):
        """min_samples may raise the bar but never weaken the trainer's own gate.

        The route used to pass its ``min_samples`` straight into the trainer,
        which has no such parameter, so a caller could neither raise nor lower
        the threshold and the route 500'd as soon as data was sufficient.
        """
        from app.ml import trainer
        from app.models.user import User
        from app.tests.conftest import mint_token, resolve_user

        owner_uid = "owner-train-test"
        owner_email = "owner-train@example.com"
        owner_id = resolve_user(db, owner_uid, owner_email)
        db.query(User).filter(User.id == owner_id).update({"role": "OWNER"})
        db.commit()
        owner_auth = {"Authorization": f"Bearer {mint_token(owner_uid, owner_email)}"}

        # 20 rows with min_samples=10 - still under the trainer's floor of 50.
        for i in range(20):
            seed_transaction(db, owner_id, amount=Decimal("100.00") + i)

        response = client.post("/api/ml/train?min_samples=10", headers=owner_auth)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["status"] == "insufficient_data"
        assert detail["required"] >= trainer.MIN_TRAIN_ROWS
        assert detail["available"] == 20

    def test_train_endpoint_really_trains_when_data_is_sufficient(
        self, client, db, tmp_path, monkeypatch
    ):
        """End-to-end proof the route is wired to the real trainer.

        The previous tests all stopped at the precheck, which is exactly why
        the broken call signature went unnoticed. This one actually fits an
        estimator and writes an artifact (into tmp_path, never the project).
        """
        from datetime import timedelta

        from app.ml import trainer
        from app.models.user import User
        from app.tests.conftest import mint_token, resolve_user

        monkeypatch.setattr(trainer, "ARTIFACT_DIR", tmp_path / "ml_artifacts")

        owner_uid = "owner-train-ok"
        owner_email = "owner-train-ok@example.com"
        owner_id = resolve_user(db, owner_uid, owner_email)
        db.query(User).filter(User.id == owner_id).update({"role": "OWNER"})
        db.commit()
        owner_auth = {"Authorization": f"Bearer {mint_token(owner_uid, owner_email)}"}

        base = datetime.utcnow().replace(microsecond=0)
        for i in range(80):
            flagged = i < 12
            seed_transaction(
                db,
                owner_id,
                amount=Decimal("25000.00") if flagged else Decimal("120.00"),
                transaction_date=base - timedelta(days=i, hours=8 if flagged else 0),
                is_flagged=flagged,
            )

        response = client.post("/api/ml/train", headers=owner_auth)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["status"] == "trained"
        assert body["rows_used"] >= 80
        assert body["positives"] >= 12
        assert body["model"] in ("xgboost", "sklearn-hist-gradient-boosting")
        assert body["artifact_path"]
        assert (tmp_path / "ml_artifacts" / "fraud_model.pkl").exists()

        metrics = {m["name"]: m["value"] for m in body["metrics"]}
        assert 0.0 <= metrics["roc_auc"] <= 1.0

        # The status endpoint must now report the model as loaded, which is
        # what switches scoring from rules_only to combined.
        status = client.get("/api/ml/status", headers=owner_auth).json()
        assert status["model_loaded"] is True
        assert status["scoring_mode"] == "combined"


class TestCategorization:
    def test_predict_from_merchant(self, client, auth):
        body = client.post(
            "/api/categorization/predict",
            headers=auth,
            json={"merchant": "SWIGGY ORDER", "amount": "450.00"},
        ).json()
        assert body["category"]
        assert body["engine"] == "keyword-rules"

    def test_categories_listing(self, client, auth):
        body = client.get("/api/categorization/categories", headers=auth).json()
        assert "Food" in body["categories"]
        assert "swiggy" in body["keywords"]["Food"]

    def test_sms_parse(self, client, auth):
        body = client.post(
            "/api/categorization/sms/parse",
            headers=auth,
            json={
                "raw_text": "HDFC Bank: Rs 1250.50 debitted at SWIGGY on 15-Jan-2026 13:22 IST. UPI Ref No 5234188."
            },
        ).json()
        assert body["amount"] == "1250.50"
        assert body["transaction_type"] == "expense"
        assert body["bank_reference"] == "5234188"

    def test_sms_commit_creates_a_transaction(self, client, auth):
        result = client.post(
            "/api/categorization/sms/commit",
            headers=auth,
            json={
                "raw_text": "ICICI Bank: Rs 500 debited to ZOMATO on 14-Jan-2026. Ref 998877."
            },
        )
        assert result.status_code == 200
        assert result.json()["created"] is True
        assert client.get("/api/transactions", headers=auth).json()["total"] == 1

    def test_ocr_requires_text(self, client, auth):
        response = client.post("/api/categorization/ocr/parse", headers=auth, json={})
        assert response.status_code == 422
        assert "OCR" in response.json()["detail"]

    def test_ocr_parse_statement(self, client, auth):
        text = (
            "STARBUCKS COFFEE\n"
            "Date: 15/01/2026\n"
            "Latte Large 350.00\n"
            "Croissant 280.00\n"
            "TOTAL 630.00\n"
        )
        body = client.post(
            "/api/categorization/ocr/parse", headers=auth, json={"text": text}
        ).json()
        assert body["parser"]
        assert body["total"] is not None or body["line_items"]


class TestLoans:
    def test_create_generates_a_schedule(self, client, auth):
        response = client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Car loan",
                "lender": "HDFC",
                "principal": "500000.00",
                "interest_rate": "8.5",
                "tenure_months": 60,
                "start_date": "2026-01-01",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["summary"]["installments_total"] == 60
        assert body["summary"]["installments_paid"] == 0
        assert float(body["monthly_emi"]) > 0
        assert len(body["upcoming"]) == 3

    def test_schedule_dates_are_clamped_to_month_length(self, client, auth):
        """A loan starting on the 31st must not produce an invalid February date."""
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Odd start",
                "principal": "120000.00",
                "interest_rate": "0.0",
                "tenure_months": 3,
                "start_date": "2026-01-31",
            },
        )
        payments = client.get(
            "/api/loans/1/payments", headers=auth
        ).json()
        assert [p["due_date"] for p in payments] == ["2026-01-31", "2026-02-28", "2026-03-31"]

    def test_emi_calculator_matches_stored_terms(self, client, auth):
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Home loan",
                "principal": "2000000.00",
                "interest_rate": "7.0",
                "tenure_months": 120,
                "start_date": "2026-01-01",
            },
        )
        stored = client.get("/api/loans/1", headers=auth).json()
        calculated = client.post(
            "/api/loans/emi/calculate",
            json={"principal": "2000000.00", "annual_rate": "7.0", "tenure_months": 120},
        ).json()
        assert stored["monthly_emi"] == calculated["monthly_emi"]

    def test_emi_calculator_with_schedule(self, client, auth):
        body = client.post(
            "/api/loans/emi/calculate",
            json={
                "principal": "100000.00",
                "annual_rate": "10.0",
                "tenure_months": 12,
                "include_schedule": True,
            },
        ).json()
        assert len(body["schedule"]) == 12
        # The principal components must sum back to the original principal.
        total_principal = sum(Decimal(str(r["principal"])) for r in body["schedule"])
        assert total_principal == Decimal("100000.00")

    def test_record_payment_closes_the_loan(self, client, auth):
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Small loan",
                "principal": "12000.00",
                "interest_rate": "0.0",
                "tenure_months": 2,
                "start_date": "2026-01-01",
            },
        )
        for installment in (1, 2):
            response = client.post(
                "/api/loans/1/payments",
                headers=auth,
                json={"installment_number": installment},
            )
            assert response.status_code == 201

        loan = client.get("/api/loans/1", headers=auth).json()
        assert loan["status"] == "CLOSED"
        assert loan["summary"]["completion_percent"] == 100.0

    def test_payment_for_unknown_installment_is_404(self, client, auth):
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Small loan",
                "principal": "12000.00",
                "interest_rate": "1.0",
                "tenure_months": 2,
                "start_date": "2026-01-01",
            },
        )
        response = client.post(
            "/api/loans/1/payments", headers=auth, json={"installment_number": 99}
        )
        assert response.status_code == 404

    def test_portfolio_totals(self, client, auth):
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Loan A",
                "principal": "100000.00",
                "interest_rate": "7.0",
                "tenure_months": 24,
                "start_date": "2026-01-01",
            },
        )
        body = client.get("/api/loans/portfolio", headers=auth).json()
        assert body["loan_count"] == 1
        assert float(body["total_outstanding"]) > 0

    def test_prepayment(self, client, auth):
        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Loan B",
                "principal": "500000.00",
                "interest_rate": "9.0",
                "tenure_months": 60,
                "start_date": "2026-01-01",
            },
        )
        body = client.get(
            "/api/loans/1/prepayment?amount=100000", headers=auth
        ).json()
        assert body["valid"] is True
        assert float(body["interest_saved"]) > 0


class TestFamily:
    def test_create_group_makes_creator_owner(self, client, auth):
        response = client.post("/api/family", headers=auth, json={"name": "Household"})
        assert response.status_code == 201
        assert response.json()["member_count"] == 1

        members = client.get(
            f"/api/family/{response.json()['id']}/members", headers=auth
        ).json()
        assert members[0]["role"] == "OWNER"
        assert members[0]["status"] == "ACTIVE"

    def test_only_group_owner_can_remove_a_member(self, client, auth, other_auth, db):
        """A plain member must not be able to evict another member.

        The guard used to fire only when the *target* held the OWNER role, so
        two ordinary members could remove each other even though the same route
        correctly blocked a non-owner from updating or deleting the group.
        """
        from app.models.user import User

        # other_auth is signed for uid-bob / bob@example.com. Create the Bob and
        # Carol accounts *before* inviting, because invite_member links the
        # invitation to a real account when the email already exists, which is
        # what makes the membership ACTIVE rather than PENDING.
        for email, uid in (("partner1@example.com", "uid-bob"), ("partner2@example.com", "uid-carol")):
            existing = db.query(User).filter(User.email == email).first()
            if existing is None:
                db.add(
                    User(email=email, name=email.split("@")[0], firebase_uid=uid, is_active=True)
                )
        db.commit()

        group = client.post("/api/family", headers=auth, json={"name": "Household"}).json()
        for email in ("partner1@example.com", "partner2@example.com"):
            assert (
                client.post(
                    f"/api/family/{group['id']}/members",
                    headers=auth,
                    json={"email": email},
                ).status_code
                == 201
            )

        members = client.get(f"/api/family/{group['id']}/members", headers=auth).json()
        assert len(members) == 3
        assert all(m["status"] == "ACTIVE" for m in members)

        target = next(m for m in members if m["invited_email"] == "partner2@example.com")

        # Bob is an ordinary MEMBER trying to remove another ordinary MEMBER.
        denied = client.delete(
            f"/api/family/{group['id']}/members/{target['id']}", headers=other_auth
        )
        assert denied.status_code == 403
        assert "owner" in denied.json()["detail"].lower()

        # The target must still be a member afterwards.
        still_there = client.get(f"/api/family/{group['id']}/members", headers=auth).json()
        assert any(m["id"] == target["id"] for m in still_there)

        # The group owner, however, can remove them.
        removed = client.delete(
            f"/api/family/{group['id']}/members/{target['id']}", headers=auth
        )
        assert removed.status_code == 204
        assert len(client.get(f"/api/family/{group['id']}/members", headers=auth).json()) == 2

    def test_member_cannot_remove_themselves(self, client, auth, other_auth, db):
        from app.models.user import User

        existing = db.query(User).filter(User.email == "partner1@example.com").first()
        if existing is None:
            db.add(
                User(
                    email="partner1@example.com",
                    name="Partner1",
                    firebase_uid="uid-bob",
                    is_active=True,
                )
            )
            db.commit()

        group = client.post("/api/family", headers=auth, json={"name": "Household"}).json()
        assert (
            client.post(
                f"/api/family/{group['id']}/members",
                headers=auth,
                json={"email": "partner1@example.com"},
            ).status_code
            == 201
        )

        members = client.get(f"/api/family/{group['id']}/members", headers=auth).json()
        own = next(m for m in members if m["invited_email"] == "partner1@example.com")

        response = client.delete(
            f"/api/family/{group['id']}/members/{own['id']}", headers=other_auth
        )
        assert response.status_code == 400

    def test_equal_split_sums_to_total(self, client, auth, db):
        from app.models.user import User

        group = client.post("/api/family", headers=auth, json={"name": "Trip"}).json()
        partner = User(email="partner@example.com", name="Partner", is_active=True)
        db.add(partner)
        db.commit()
        db.refresh(partner)

        invited = client.post(
            f"/api/family/{group['id']}/members",
            headers=auth,
            json={"email": "partner@example.com"},
        )
        assert invited.status_code == 201
        assert invited.json()["status"] == "ACTIVE"

        expense = client.post(
            f"/api/family/{group['id']}/expenses",
            headers=auth,
            json={
                "title": "Hotel",
                "total_amount": "1000.00",
                "expense_date": datetime.utcnow().isoformat(),
                "equal_split": True,
            },
        )
        assert expense.status_code == 201
        assert expense.json()["split_count"] == 2

        splits = client.get(
            f"/api/family/{group['id']}/expenses/{expense.json()['id']}/splits",
            headers=auth,
        ).json()
        assert sum(Decimal(str(s["owed_amount"])) for s in splits) == Decimal("1000.00")

    def test_uneven_split_must_add_up(self, client, auth, db):
        from app.models.user import User

        group = client.post("/api/family", headers=auth, json={"name": "Trip"}).json()
        partner = User(email="p2@example.com", name="P2", is_active=True)
        db.add(partner)
        db.commit()
        db.refresh(partner)
        client.post(
            f"/api/family/{group['id']}/members",
            headers=auth,
            json={"email": "p2@example.com"},
        )

        response = client.post(
            f"/api/family/{group['id']}/expenses",
            headers=auth,
            json={
                "title": "Bad split",
                "total_amount": "1000.00",
                "expense_date": datetime.utcnow().isoformat(),
                "equal_split": False,
                "splits": [{"user_id": 1, "amount": "400.00"}],
            },
        )
        assert response.status_code == 422
        assert "do not add up" in response.json()["detail"]

    def test_non_member_cannot_update_group(self, client, auth, other_auth):
        """A non-member is refused before the owner check is even reached."""
        group = client.post("/api/family", headers=auth, json={"name": "Shared"}).json()
        response = client.patch(
            f"/api/family/{group['id']}", headers=other_auth, json={"name": "Hijacked"}
        )
        assert response.status_code == 404

    def test_non_owner_member_cannot_update_group(self, client, auth, other_auth, db):
        """A real member who is not the owner gets 403, not 404."""
        from app.models.user import User

        group = client.post("/api/family", headers=auth, json={"name": "Shared"}).json()
        partner = User(
            email="p3@example.com",
            name="P3",
            firebase_uid="uid-bob",
            is_active=True,
        )
        db.add(partner)
        db.commit()
        db.refresh(partner)
        client.post(
            f"/api/family/{group['id']}/members",
            headers=auth,
            json={"email": "p3@example.com"},
        )

        response = client.patch(
            f"/api/family/{group['id']}", headers=other_auth, json={"name": "Hijacked"}
        )
        assert response.status_code == 403

        # The group is unchanged.
        assert client.get(f"/api/family/{group['id']}", headers=auth).json()["name"] == "Shared"

    def test_balances_reconcile(self, client, auth, db):
        from app.models.user import User

        group = client.post("/api/family", headers=auth, json={"name": "Shared"}).json()
        partner = User(email="p4@example.com", name="P4", is_active=True)
        db.add(partner)
        db.commit()
        db.refresh(partner)
        client.post(
            f"/api/family/{group['id']}/members",
            headers=auth,
            json={"email": "p4@example.com"},
        )
        client.post(
            f"/api/family/{group['id']}/expenses",
            headers=auth,
            json={
                "title": "Dinner",
                "total_amount": "600.00",
                "expense_date": datetime.utcnow().isoformat(),
                "equal_split": True,
            },
        )

        balances = client.get(f"/api/family/{group['id']}/balances", headers=auth).json()
        # Alice paid 600, so she is owed 300 and Bob owes 300.
        assert sum(Decimal(str(b["net"])) for b in balances) == Decimal("0.00")
        assert any(Decimal(str(b["owed_to_you"])) == Decimal("300.00") for b in balances)

    def test_duplicate_invite_is_rejected(self, client, auth):
        group = client.post("/api/family", headers=auth, json={"name": "Shared"}).json()
        payload = {"email": "new@example.com"}
        assert client.post(
            f"/api/family/{group['id']}/members", headers=auth, json=payload
        ).status_code == 201
        assert client.post(
            f"/api/family/{group['id']}/members", headers=auth, json=payload
        ).status_code == 409


class TestNotifications:
    def test_create_and_mark_read(self, client, auth):
        created = client.post(
            "/api/notifications",
            headers=auth,
            json={"title": "Budget exceeded", "body": "You are over budget on Food."},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["notification"]["title"] == "Budget exceeded"

        count = client.get("/api/notifications/unread-count", headers=auth).json()
        assert count["unread"] == 1

        read = client.post(
            f"/api/notifications/{body['notification']['id']}/read", headers=auth
        )
        assert read.json()["is_read"] is True

    def test_title_is_required(self, client, auth):
        assert client.post(
            "/api/notifications", headers=auth, json={"body": "no title"}
        ).status_code == 422

    def test_device_registration_is_idempotent(self, client, auth):
        payload = {
            "token": "fcm-token-abcdef123456",
            "platform": "ANDROID",
            "device_name": "Pixel",
        }
        first = client.post("/api/notifications/devices", headers=auth, json=payload)
        second = client.post("/api/notifications/devices", headers=auth, json=payload)
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert len(client.get("/api/notifications/devices", headers=auth).json()) == 1

    def test_test_push_reports_that_nothing_was_sent(self, client, auth):
        """FCM is unconfigured, so the endpoint must say so rather than lie."""
        body = client.post("/api/notifications/devices/test", headers=auth).json()
        assert body["success_count"] == 0
        assert body["provider"] == "none"
        assert "not configured" in body["message"]


class TestBackup:
    def test_providers_are_reported_honestly(self, client, auth):
        body = client.get("/api/backups/providers", headers=auth).json()
        assert set(body["providers"]) == {
            "FIREBASE_STORAGE", "GOOGLE_CLOUD_STORAGE", "GOOGLE_DRIVE"
        }
        # No cloud credentials exist in the test environment.
        assert body["cloud_configured"] is False
        assert body["default_provider"] == "LOCAL"
        assert "No cloud backup provider is configured" in body["message"]

    def test_unconfigured_provider_fails_loudly(self, client, auth):
        response = client.post(
            "/api/backups", headers=auth, json={"provider": "GOOGLE_CLOUD_STORAGE"}
        )
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["error"] == "Backup failed."
        assert "not configured" in detail["reason"]

    def test_local_backup_succeeds_and_is_verifiable(self, client, auth):
        client.post("/api/transactions", headers=auth, json=tx_payload())
        created = client.post("/api/backups", headers=auth, json={})
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "SUCCESS"
        assert body["record_count"] == 1
        assert body["size_bytes"] > 0
        assert body["checksum"]

        verified = client.post(f"/api/backups/{body['id']}/verify", headers=auth).json()
        assert verified["verified"] is True

    def test_failed_backup_is_still_recorded(self, client, auth):
        client.post("/api/backups", headers=auth, json={"provider": "GOOGLE_DRIVE"})
        history = client.get("/api/backups", headers=auth).json()
        assert history["total"] == 1
        assert history["items"][0]["status"] == "FAILED"
        assert history["items"][0]["error_message"]

    def test_backup_history_is_per_user(self, client, auth, other_auth):
        client.post("/api/backups", headers=auth, json={})
        assert client.get("/api/backups", headers=other_auth).json()["total"] == 0


class TestReports:
    @pytest.mark.parametrize("report_format", ["CSV", "EXCEL", "PDF"])
    def test_all_formats_generate(self, client, auth, report_format):
        client.post("/api/transactions", headers=auth, json=tx_payload())
        response = client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "TRANSACTIONS", "report_format": report_format},
        )
        assert response.status_code == 200
        assert len(response.content) > 0
        assert "attachment" in response.headers["content-disposition"]
        assert response.headers["x-row-count"] == "1"

    def test_csv_content_is_readable(self, client, auth):
        client.post("/api/transactions", headers=auth, json=tx_payload())
        response = client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "TRANSACTIONS", "report_format": "CSV"},
        )
        text = response.content.decode("utf-8")
        assert "Corner Cafe" in text
        assert text.splitlines()[0].startswith("id,transaction_date")

    def test_category_report(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        seed_transaction(db, uid, category="Food", amount=Decimal("100.00"))
        response = client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "CATEGORIES", "report_format": "CSV"},
        )
        assert response.status_code == 200
        assert "Food" in response.content.decode("utf-8")

    def test_income_report_excludes_expenses(self, client, auth):
        from app.models.transaction import TransactionType

        client.post("/api/transactions", headers=auth, json=tx_payload())
        client.post(
            "/api/transactions",
            headers=auth,
            json=tx_payload(transaction_type="income", category="Salary"),
        )
        response = client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "INCOME", "report_format": "CSV"},
        )
        assert response.headers["x-row-count"] == "1"
        assert "Salary" in response.content.decode("utf-8")

    def test_report_history_is_recorded(self, client, auth):
        client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "TRANSACTIONS", "report_format": "CSV"},
        )
        history = client.get("/api/reports", headers=auth).json()
        assert len(history) == 1
        assert history[0]["report_type"] == "TRANSACTIONS"

    def test_invalid_format_is_rejected(self, client, auth):
        response = client.post(
            "/api/reports/generate",
            headers=auth,
            json={"report_type": "TRANSACTIONS", "report_format": "DOCX"},
        )
        assert response.status_code == 422


class TestAssistant:
    def test_answers_from_own_data(self, client, auth, db):
        from app.models.transaction import TransactionType
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        now = datetime.utcnow()
        seed_transaction(
            db, uid, category="Food", amount=Decimal("400.00"), transaction_date=now,
            transaction_type=TransactionType.EXPENSE,
        )
        seed_transaction(
            db, uid, category="Salary", amount=Decimal("1000.00"), transaction_date=now,
            transaction_type=TransactionType.INCOME,
        )

        body = client.post(
            "/api/assistant", headers=auth, json={"message": "How much did I spend?"}
        ).json()
        assert "400" in body["reply"]
        assert body["provider"] == "builtin"
        assert body["suggestions"]

    def test_config_declares_the_engine(self, client, auth):
        body = client.get("/api/assistant/config", headers=auth).json()
        assert body["provider"] == "builtin"
        assert body["remote_configured"] is False
        assert "ASSISTANT_API_KEY" in body["message"]

    def test_unknown_question_admits_it(self, client, auth):
        body = client.post(
            "/api/assistant", headers=auth, json={"message": "qwertyuiop asdfgh"}
        ).json()
        assert "did not recognise" in body["reply"]

    def test_context_lines_are_returned(self, client, auth):
        client.post("/api/transactions", headers=auth, json=tx_payload())
        body = client.post(
            "/api/assistant",
            headers=auth,
            json={"message": "What is my savings rate?", "include_context": True},
        ).json()
        assert any("Income" in line for line in body["context_used"])

    def test_budget_question(self, client, auth, db):
        from app.tests.conftest import resolve_user

        uid = resolve_user(db, "uid-alice", "alice@example.com")
        now = datetime.utcnow()
        seed_budget(db, uid, month=now.month, year=now.year)
        body = client.post(
            "/api/assistant", headers=auth, json={"message": "am I over budget?"}
        ).json()
        assert "budget" in body["reply"].lower()


class TestMeta:
    def test_root_and_health(self, client):
        assert client.get("/").json()["version"] == "2.0.0"
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["database"]["connected"] is True

    def test_health_does_not_leak_configuration(self, client):
        """``/health`` is unauthenticated, so it must not describe the deployment.

        A database error string can echo the host, port and credentials the DSN
        was built from, and the database name alone tells an attacker which
        instance to target. Only booleans belong on this endpoint.
        """
        from app.core.config import settings

        response = client.get("/health")
        body = response.json()
        database = body["database"]

        assert "name" not in database
        assert "dsn" not in database
        assert "url" not in database
        assert "error" not in database
        assert settings.db_name not in response.text

        # ...while the genuinely useful signals are still reported.
        assert isinstance(body["auth"]["firebase_enabled"], bool)
        assert isinstance(body["auth"]["dev_auth_active"], bool)

    def test_health_reports_error_type_not_error_text(self, client, monkeypatch):
        """A failing database must 503 without echoing the connection string."""
        import main as main_module

        def boom():
            raise RuntimeError(
                f"connection refused at {main_module.settings.db_host}:"
                f"{main_module.settings.db_port} for {main_module.settings.db_user}"
            )

        monkeypatch.setattr(main_module, "engine", _FailingEngine(boom))
        monkeypatch.setattr(main_module, "text", lambda *a, **k: "SELECT 1")

        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"]["connected"] is False
        assert body["database"]["error_type"] == "RuntimeError"

        raw = response.text
        assert "refused" not in raw
        assert main_module.settings.db_user not in raw
        assert main_module.settings.db_password not in raw

    def test_api_info_lists_features(self, client):
        features = client.get("/api/info").json()["features"]
        assert features["assistant"] is True
        assert features["cloud_backup"] is True

    def test_openapi_schema_is_valid(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert "paths" in spec
        assert len(spec["paths"]) > 50

    def test_cors_is_not_wildcard(self, client):
        response = client.get(
            "/api/auth/config", headers={"Origin": "http://evil.example.com"}
        )
        assert "access-control-allow-origin" not in response.headers
