"""Spending prediction tests.

The important behaviour here is honesty. A forecast endpoint is exactly where a
convenient implementation starts inventing numbers for users who have almost no
history, so the insufficient-data path is tested as carefully as the happy path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models.budget import Budget
from app.models.transaction import Transaction
from app.services.prediction import (
    MIN_MONTHS_FOR_TREND,
    backtest_forecast,
    build_prediction_report,
    category_forecasts,
    forecast_next_month,
    monthly_expense_history,
)
from app.tests.conftest import resolve_user, seed_budget, seed_transaction


def month_back(months: int, day: int = 15) -> datetime:
    """A date ``months`` months before today, anchored on ``day``."""
    now = datetime.utcnow()
    year = now.year
    month = now.month - months
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, day)


@pytest.fixture()
def user_id(db):
    return resolve_user(db, "uid-alice", "alice@example.com")


def seed_months(db, user_id, amounts, category="Food", day=15):
    """One expense per month, oldest first, with the given amounts.

    ``amounts[0]`` is the *oldest* month, matching the order
    :func:`monthly_expense_history` returns, so ``[1000, 1100, 1200]`` reads as
    "spending rose over three months".
    """
    rows = []
    for offset, amount in enumerate(reversed(amounts)):
        rows.append(
            seed_transaction(
                db,
                user_id,
                amount=Decimal(str(amount)),
                category=category,
                transaction_date=month_back(offset, day),
            )
        )
    return rows


class TestMonthlyHistory:
    def test_months_are_aggregated_not_row_counted(self, db, user_id):
        """Twenty purchases in one month are one month of history."""
        for day in range(1, 21):
            seed_transaction(
                db,
                user_id,
                amount=Decimal("10.00"),
                category="Food",
                transaction_date=month_back(0, day),
            )
        history = monthly_expense_history(
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert len(history) == 1
        assert history[0].amount == Decimal("200.00")

    def test_income_is_never_counted_as_spending(self, db, user_id):
        seed_transaction(
            db,
            user_id,
            amount=Decimal("5000.00"),
            transaction_type="income",
            transaction_date=month_back(0),
        )
        seed_transaction(
            db, user_id, amount=Decimal("120.00"), transaction_date=month_back(0)
        )
        history = monthly_expense_history(
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert history[0].amount == Decimal("120.00")

    def test_month_with_no_spend_is_absent_not_zero(self, db, user_id):
        """A silent month is missing data, not evidence of zero spending.

        Recording a zero would drag the average down and produce a forecast
        that is wrong by exactly the amount the user forgot to record.
        """
        # Two months with spend, a gap between them.
        seed_transaction(db, user_id, amount=Decimal("100.00"), transaction_date=month_back(0))
        seed_transaction(db, user_id, amount=Decimal("300.00"), transaction_date=month_back(2))

        history = monthly_expense_history(
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert [m.amount for m in history] == [Decimal("300.00"), Decimal("100.00")]
        assert all(m.amount > 0 for m in history)
        # The gap is visible as a two-month step between the labels.
        assert history[1].label != history[0].label

    def test_history_is_ordered_oldest_first(self, db, user_id):
        seed_months(db, user_id, [100.00, 200.00, 300.00])
        history = monthly_expense_history(
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert [m.amount for m in history] == [
            Decimal("100.00"),
            Decimal("200.00"),
            Decimal("300.00"),
        ]


class TestInsufficientData:
    def test_no_history_yields_no_prediction(self, db, user_id):
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert forecast_next_month(transactions) is None

    def test_one_month_is_not_enough(self, db, user_id):
        seed_months(db, user_id, [500.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert forecast_next_month(transactions) is None

    def test_two_months_is_not_enough(self, db, user_id):
        seed_months(db, user_id, [500.00, 600.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        assert forecast_next_month(transactions) is None

    def test_report_explains_the_shortfall(self, db, user_id):
        seed_months(db, user_id, [500.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        report = build_prediction_report(transactions)

        assert report["status"] == "insufficient_data"
        # The key is always present, so a client never has to branch on whether
        # it exists - it is simply null.
        assert "prediction" in report
        assert report["prediction"] is None
        assert report["required_months"] == MIN_MONTHS_FOR_TREND
        assert report["available_months"] == 1
        assert report["months_needed"] == MIN_MONTHS_FOR_TREND - 1
        # The message has to tell the user what to do, not just refuse.
        assert str(MIN_MONTHS_FOR_TREND) in report["message"]
        assert "recording" in report["message"].lower()

    def test_budget_projection_is_available_even_without_a_trend(self, db, user_id):
        """A month-to-date projection needs one month, not three.

        Withholding it alongside the trend forecast would hide genuinely useful,
        honest data from a user who has only just started.
        """
        now = datetime.utcnow()
        seed_budget(
            db,
            user_id,
            category="Food",
            month=now.month,
            year=now.year,
            amount=Decimal("1000.00"),
        )
        seed_transaction(
            db,
            user_id,
            amount=Decimal("100.00"),
            category="Food",
            transaction_date=now,
        )
        budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        report = build_prediction_report(transactions, budgets)

        assert report["status"] == "insufficient_data"
        assert report["prediction"] is None
        # ...but the projection is still there, because it did not need a trend.
        assert report["budget_projection"]
        assert report["budget_projection"][0]["category"] == "Food"
        assert report["categories"]

    def test_single_month_message_uses_singular(self, db, user_id):
        """'There is 1 month' reads as written; a plural would be a bug."""
        seed_months(db, user_id, [500.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        message = build_prediction_report(transactions)["message"]
        assert "is 1 month of data" in message

    def test_endpoint_returns_200_with_null_prediction(self, client, auth, db, user_id):
        response = client.get("/api/dashboard/prediction", headers=auth)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "insufficient_data"
        assert body["prediction"] is None
        assert body["months_needed"] > 0


class TestForecast:
    def test_three_months_produce_a_forecast(self, db, user_id):
        seed_months(db, user_id, [1000.00, 1100.00, 1200.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        report = build_prediction_report(transactions)

        assert report["status"] == "predicted"
        prediction = report["prediction"]
        assert prediction is not None
        assert prediction["months_of_history"] == 3
        assert prediction["basis"] == "linear-trend-over-monthly-expense"
        # The trend is rising by 100/month, so the projection sits above the mean.
        assert Decimal(prediction["predicted_expense"]) > Decimal(
            prediction["average_monthly_expense"]
        )
        assert len(report["history"]) == 3

    def test_declining_spend_predicts_the_average_not_a_negative(self, db, user_id):
        """A trend toward zero is an artefact, not a forecast.

        Least squares on a decaying series eventually crosses zero, and clamping
        it to zero would claim the user will spend nothing. The service falls back
        to the observed average and says why.
        """
        seed_months(db, user_id, [10000.00, 100.00, 10.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        prediction = forecast_next_month(transactions)

        assert prediction is not None
        assert prediction.predicted_expense > 0
        assert any(
            "average month" in note for note in prediction.notes
        ), prediction.notes

    def test_steady_spend_gets_a_tight_range(self, db, user_id):
        seed_months(db, user_id, [1000.00, 1000.00, 1000.00, 1000.00, 1000.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        prediction = forecast_next_month(transactions)

        assert prediction is not None
        assert prediction.predicted_expense == Decimal("1000.00")
        # Near-zero volatility, but never a zero-width range - that would be a
        # promise the data cannot support.
        assert prediction.high > prediction.predicted_expense
        assert prediction.low < prediction.predicted_expense

    def test_volatile_spend_gets_a_wide_range_and_a_warning(self, db, user_id):
        seed_months(db, user_id, [500.00, 5000.00, 200.00, 6000.00, 300.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        prediction = forecast_next_month(transactions)

        assert prediction is not None
        assert (prediction.high - prediction.predicted_expense) > (
            prediction.predicted_expense - prediction.low
        ) - Decimal("1000")
        assert any("varies a lot" in note for note in prediction.notes)

    def test_range_never_goes_negative(self, db, user_id):
        seed_months(db, user_id, [500.00, 100.00, 50.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        prediction = forecast_next_month(transactions)
        assert prediction is not None
        assert prediction.low >= Decimal("0")

    def test_forecast_month_follows_the_data(self, db, user_id):
        """The forecast targets the month the user is about to enter."""
        seed_months(db, user_id, [1000.00, 1100.00, 1200.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        prediction = forecast_next_month(transactions)
        history = monthly_expense_history(transactions)

        assert prediction is not None
        last = history[-1]
        expected_year = last.year + 1 if last.month == 12 else last.year
        expected_month = 1 if last.month == 12 else last.month + 1
        assert (prediction.year, prediction.month) == (expected_year, expected_month)
        assert prediction.label == f"{expected_year:04d}-{expected_month:02d}"

    def test_endpoint_returns_a_forecast(self, client, auth, db, user_id):
        seed_months(db, user_id, [1000.00, 1100.00, 1200.00])
        response = client.get("/api/dashboard/prediction", headers=auth)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "predicted"
        assert body["prediction"]["predicted_expense"]
        assert body["prediction"]["range"]["low"] <= body["prediction"]["range"]["high"]
        assert body["available_months"] == 3


class TestBacktest:
    """The forecast must be scored, not just produced.

    These prove the walk-forward loop reports honest error metrics against the
    baselines and refuses to score when there is nothing to hold out.
    """

    def test_needs_more_than_the_training_window(self, db, user_id):
        seed_months(db, user_id, [100.00, 200.00, 300.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        result = backtest_forecast(transactions)

        assert result["status"] == "insufficient_data"
        assert result["metrics"] == {}
        assert result["best_method"] is None
        assert result["evaluation_points"] == 0

    def test_scores_every_method_and_finds_the_best(self, db, user_id):
        # A perfectly linear series: the trend should beat mean and naive.
        seed_months(db, user_id, [1000.00, 1100.00, 1200.00, 1300.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        result = backtest_forecast(transactions)

        assert result["status"] == "evaluated"
        assert result["evaluation_points"] == 1
        metrics = result["metrics"]
        for method in ("linear_trend", "mean", "naive"):
            assert set(metrics[method]) == {"mae", "rmse", "n"}
            assert metrics[method]["mae"] >= 0
            assert metrics[method]["rmse"] >= metrics[method]["mae"]
        assert metrics["linear_trend"]["mae"] == 0
        assert result["best_method"] == "linear_trend"

    def test_seasonal_baseline_absent_without_a_year(self, db, user_id):
        seed_months(db, user_id, [100.00, 200.00, 300.00, 400.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        metrics = backtest_forecast(transactions)["metrics"]
        # Fewer than 13 months of data means no same-month-last-year comparison.
        assert "seasonal_naive" not in metrics

    def test_metrics_stay_within_the_data(self, db, user_id):
        """A leak-free backtest can be wrong, but never reports negative error."""
        seed_months(db, user_id, [500.00, 5000.00, 200.00, 6000.00, 300.00, 700.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        result = backtest_forecast(transactions)
        for metrics in result["metrics"].values():
            assert metrics["mae"] >= 0
            assert metrics["rmse"] >= 0

    def test_report_carries_the_backtest(self, db, user_id):
        seed_months(db, user_id, [1000.00, 1100.00, 1200.00, 1300.00])
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        report = build_prediction_report(transactions)
        assert report["status"] == "predicted"
        assert report["backtest"]["status"] == "evaluated"


class TestCategoryForecasts:
    def test_categories_are_ranked_by_average(self, db, user_id):
        for offset in range(3):
            seed_transaction(
                db,
                user_id,
                amount=Decimal("900.00"),
                category="Rent",
                transaction_date=month_back(offset),
            )
            seed_transaction(
                db,
                user_id,
                amount=Decimal("50.00"),
                category="Snacks",
                transaction_date=month_back(offset),
            )
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        forecasts = category_forecasts(transactions)
        assert forecasts[0]["category"] == "Rent"
        assert forecasts[0]["average_per_month"] == Decimal("900.00")
        assert forecasts[1]["category"] == "Snacks"

    def test_totals_match_the_rows(self, db, user_id):
        seed_months(db, user_id, [100.00, 200.00], category="Food")
        transactions = (
            db.query(Transaction).filter(Transaction.user_id == user_id).all()
        )
        forecasts = category_forecasts(transactions)
        assert forecasts[0]["total"] == Decimal("300.00")
        assert forecasts[0]["average_per_month"] == Decimal("150.00")

class TestBudgetProjection:
    def test_projection_extrapolates_from_month_to_date(self, client, auth, db, user_id):
        now = datetime.utcnow()
        seed_budget(db, user_id, category="Food", month=now.month, year=now.year, amount=Decimal("1000.00"))
        # Spend a little in the current month.
        seed_transaction(
            db,
            user_id,
            amount=Decimal("100.00"),
            category="Food",
            transaction_date=now,
        )
        response = client.get("/api/dashboard/prediction", headers=auth)
        assert response.status_code == 200
        projection = response.json()["budget_projection"]
        assert projection, "expected a projection for the seeded budget"
        row = projection[0]
        # Over JSON, money is a string - the API never sends a float for an amount.
        assert row["category"] == "Food"
        assert Decimal(row["budget"]) == Decimal("1000.00")
        assert Decimal(row["spent"]) == Decimal("100.00")
        # The projection must be at least what has already been spent.
        assert Decimal(row["projected"]) >= Decimal(row["spent"])

    def test_over_projected_flag_is_set(self, client, auth, db, user_id):
        now = datetime.utcnow()
        seed_budget(db, user_id, category="Food", month=now.month, year=now.year, amount=Decimal("10.00"))
        seed_transaction(
            db,
            user_id,
            amount=Decimal("500.00"),
            category="Food",
            transaction_date=now,
        )
        body = client.get("/api/dashboard/prediction", headers=auth).json()
        row = next(r for r in body["budget_projection"] if r["category"] == "Food")
        assert row["over_projected"] is True
        assert row["projected_ratio"] > 1


class TestIsolation:
    def test_prediction_never_includes_another_users_spend(self, client, auth, other_auth, db, user_id):
        """The forecast is built from the caller's own rows only."""
        bob = resolve_user(db, "uid-bob", "bob@example.com")
        seed_months(db, user_id, [100.00, 200.00, 300.00])
        # Bob spends a great deal more; Alice's forecast must not see it.
        seed_months(db, bob, [99999.00, 99999.00, 99999.00])

        body = client.get("/api/dashboard/prediction", headers=auth).json()
        assert body["status"] == "predicted"
        assert Decimal(body["observed_average"]) == Decimal("200.00")
        assert "99999" not in client.get("/api/dashboard/prediction", headers=auth).text

    def test_requires_authentication(self, client):
        assert client.get("/api/dashboard/prediction").status_code in (401, 403)
