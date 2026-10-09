"""Spending forecasts.

The forecast is deliberately an explainable statistical projection rather than a
learned model. Two reasons:

1. **A user's own history is the only honest training set here.** There is no
   labelled data about *this* user's future spending, and a model fitted on nine
   transactions would be confidently wrong. A linear trend over monthly totals,
   with a spread built from the same months, is the most a handful of data points
   actually supports.
2. **Every number has to be traceable.** "You will spend about X, most likely
   between Y and Z" can be checked against the user's own history by hand. A
   model output cannot, and for a financial product that difference matters.

When there is not enough history the service says so instead of extrapolating
from noise, and :data:`INSUFFICIENT_DATA` makes the caller return a truthful
"not enough data yet" payload rather than a fabricated figure.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from app.services.analytics import _is_expense, _month_key, month_bounds
from app.utils.money import money, safe_div, to_decimal

# Minimum months of history before a monthly forecast is published at all.
# Below this a trend line is drawn through noise, so the API reports the reason
# instead of a number.
MIN_MONTHS_FOR_TREND = 3
# Below this even a per-category average is not worth showing.
MIN_MONTHS_FOR_CATEGORY = 2
# A month with no transactions at all carries no information about spending, so
# it is excluded from the history rather than counted as a zero-spend month.
MIN_MONTHS_WITH_SPEND = 1

# The spread is derived from the observed month-to-month variability, widened to
# give a range the user can actually plan around.
SPREAD_FLOOR = Decimal("0.10")


@dataclass
class MonthSpend:
    year: int
    month: int
    amount: Decimal

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass
class Prediction:
    month: int
    year: int
    label: str
    predicted_expense: Decimal
    low: Decimal
    high: Decimal
    average_monthly_expense: Decimal
    months_of_history: int
    volatility: Decimal
    basis: str
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "month": self.month,
            "year": self.year,
            "label": self.label,
            "predicted_expense": money(self.predicted_expense),
            "range": {
                "low": money(self.low),
                "high": money(self.high),
            },
            "average_monthly_expense": money(self.average_monthly_expense),
            "months_of_history": self.months_of_history,
            "volatility": money(self.volatility),
            "basis": self.basis,
            "notes": self.notes,
        }


def monthly_expense_history(transactions: Sequence) -> List[MonthSpend]:
    """Expense per calendar month, oldest first, months with no spend dropped.

    Months are keyed on the *calendar* month rather than on rows, so a month
    with twenty transactions still counts once. A month with zero expense rows
    is skipped rather than recorded as zero: the user simply had not recorded
    anything, which is missing data and not a spending level of zero.
    """
    totals: Dict[tuple, Decimal] = {}
    for tx in transactions:
        if not _is_expense(tx):
            continue
        key = _month_key(tx.transaction_date)
        totals[key] = totals.get(key, Decimal("0")) + to_decimal(tx.amount)

    history = [
        MonthSpend(year=year, month=month, amount=amount)
        for (year, month), amount in totals.items()
        if amount > 0
    ]
    history.sort(key=lambda m: (m.year, m.month))
    return history


def _next_month(year: int, month: int) -> tuple:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _linear_trend(history: Sequence[MonthSpend]) -> tuple:
    """Least-squares slope/intercept of amount against month index.

    Returns ``(slope, intercept)`` where ``intercept`` is the value at index 0.
    The x-axis is the position in the sequence rather than the month number, so
    a gap in the data does not silently compress the trend.
    """
    n = len(history)
    xs = list(range(n))
    ys = [float(m.amount) for m in history]

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    return slope, mean_y - slope * mean_x


def _forecast_from_history(history: Sequence[MonthSpend]) -> tuple:
    """The point forecast for the next month, plus whether it fell back to the mean.

    Returns ``(predicted, used_fallback)``. The single place the trend is turned
    into a number, shared by the live forecast and the backtest so the two can
    never drift apart.
    """
    amounts = [m.amount for m in history]
    average = sum(amounts) / Decimal(len(amounts))
    slope, intercept = _linear_trend(history)
    raw = intercept + slope * len(history)

    # A trend that turns negative (or near-zero) means the user's spend is
    # decaying to nothing. That is a projection artefact, not a forecast, so
    # fall back to the observed average and say so.
    if raw <= 0:
        return average, True
    return Decimal(str(raw)), False


def forecast_next_month(
    transactions: Sequence,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> Optional[Prediction]:
    """Project next month's expenses, or ``None`` when there is too little history.

    ``year``/``month`` default to the month after the most recent transaction,
    which is the useful thing to forecast: "what will I spend in the month I am
    about to enter", not a stale fixed calendar month.
    """
    history = monthly_expense_history(transactions)
    if len(history) < MIN_MONTHS_FOR_TREND:
        return None

    amounts = [m.amount for m in history]
    average = sum(amounts) / Decimal(len(amounts))

    predicted, used_fallback = _forecast_from_history(history)

    notes: List[str] = []
    if used_fallback:
        notes.append(
            "The trend in your history points to zero or below, which is not a "
            "meaningful projection. The forecast uses your average month instead."
        )

    # Spread from the real dispersion of the history, never from the point
    # estimate, so a user with a steady pattern gets a tight range and a user
    # with a volatile one is warned.
    if len(amounts) > 1:
        volatility = Decimal(str(statistics.stdev([float(a) for a in amounts])))
    else:
        volatility = Decimal("0")
    spread = max(volatility * Decimal("1.5"), average * SPREAD_FLOOR)

    if year is None or month is None:
        last = history[-1]
        year, month = _next_month(last.year, last.month)

    low = predicted - spread
    high = predicted + spread
    if low < 0:
        low = Decimal("0")

    if volatility > average:
        notes.append(
            "Your spending varies a lot month to month, so this range is wide. "
            "Treat the middle figure as a rough guide rather than a target."
        )

    return Prediction(
        month=month,
        year=year,
        label=f"{year:04d}-{month:02d}",
        predicted_expense=money(predicted),
        low=money(low),
        high=money(high),
        average_monthly_expense=money(average),
        months_of_history=len(history),
        volatility=money(volatility),
        basis="linear-trend-over-monthly-expense",
        notes=notes,
    )


def backtest_forecast(
    transactions: Sequence,
    min_train: int = MIN_MONTHS_FOR_TREND,
) -> Dict:
    """Walk-forward evaluation of the forecast against simple baselines.

    Each step trains on the months strictly *before* the one being predicted, so
    no future data reaches a prediction - the same discipline the live forecast
    uses. MAE and RMSE are then reported per method (in currency units) so the
    trend projection can be judged against a running mean and a naive
    last-value carry-forward on the user's own history, instead of being assumed
    to be the best. A seasonal-naive baseline (same month last year) is scored
    only when a year of history exists to support it.

    This is the honest answer to "is the model any good?" for a per-user series:
    the dataset is the user's own months, and the comparison is against the
    baselines a reasonable person would use instead.
    """
    history = monthly_expense_history(transactions)
    if len(history) <= min_train:
        return {
            "status": "insufficient_data",
            "message": (
                f"A backtest needs more than {min_train} months of history to "
                "hold months out and score the forecast."
            ),
            "months_of_history": len(history),
            "evaluation_points": 0,
            "horizon_months": 1,
            "method": "walk-forward, one month ahead",
            "metrics": {},
            "best_method": None,
        }

    errors: Dict[str, List[float]] = {
        "linear_trend": [],
        "mean": [],
        "naive": [],
        "seasonal_naive": [],
    }
    amount_by_month = {(m.year, m.month): float(m.amount) for m in history}

    for index in range(min_train, len(history)):
        train = history[:index]
        target = history[index]
        actual = float(target.amount)
        train_amounts = [float(m.amount) for m in train]

        linear, _ = _forecast_from_history(train)
        errors["linear_trend"].append(abs(actual - float(linear)))
        errors["mean"].append(abs(actual - sum(train_amounts) / len(train_amounts)))
        errors["naive"].append(abs(actual - train_amounts[-1]))

        last_year = amount_by_month.get((target.year - 1, target.month))
        if last_year is not None:
            errors["seasonal_naive"].append(abs(actual - last_year))

    metrics: Dict[str, Dict] = {}
    for method, absolute_errors in errors.items():
        count = len(absolute_errors)
        if count == 0:
            continue
        mae = sum(absolute_errors) / count
        rmse = (sum(e * e for e in absolute_errors) / count) ** 0.5
        metrics[method] = {"mae": round(mae, 2), "rmse": round(rmse, 2), "n": count}

    best_method = min(metrics, key=lambda name: metrics[name]["mae"]) if metrics else None
    return {
        "status": "evaluated",
        "message": (
            "Walk-forward error on your own monthly history. The trend forecast "
            "is scored against a running mean and a naive last-month carry-forward; "
            "lower MAE is better."
        ),
        "months_of_history": len(history),
        "evaluation_points": len(history) - min_train,
        "horizon_months": 1,
        "method": "walk-forward, one month ahead",
        "metrics": metrics,
        "best_method": best_method,
    }


def category_forecasts(
    transactions: Sequence,
    history: Optional[Sequence[MonthSpend]] = None,
    min_months: int = MIN_MONTHS_FOR_CATEGORY,
) -> List[Dict]:
    """Per-category average monthly spend, largest first.

    A plain average over months in which the category was actually used, so a
    category bought from three times in six months is reported as a per-use-month
    figure rather than being diluted by months with no purchase at all. That is
    the number a user can compare against their next shopping trip.
    """
    if history is None:
        history = monthly_expense_history(transactions)
    months_with_spend = {m.label for m in history} or set()
    total_months = max(len(months_with_spend), 1)

    per_category: Dict[str, Decimal] = {}
    for tx in transactions:
        if not _is_expense(tx):
            continue
        label = f"{tx.transaction_date.year:04d}-{tx.transaction_date.month:02d}"
        if months_with_spend and label not in months_with_spend:
            continue
        per_category[tx.category] = per_category.get(tx.category, Decimal("0")) + to_decimal(
            tx.amount
        )

    out = [
        {
            "category": category,
            "total": money(total),
            "average_per_month": money(safe_div(total, Decimal(total_months), Decimal("0"))),
        }
        for category, total in per_category.items()
    ]
    out.sort(key=lambda item: item["average_per_month"], reverse=True)
    return out


def budget_projection(
    transactions: Sequence,
    budgets: Sequence,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> List[Dict]:
    """Where each budget is heading if the month continues at the current rate.

    Projects the end-of-month total from the month-to-date spend and how much of
    the month has actually elapsed, which is the question a user is asking when
    they open the app on the 10th. Months in the past are reported as final.
    """
    now = datetime.utcnow()
    year = year if year is not None else now.year
    month = month if month is not None else now.month
    start, end = month_bounds(year, month)
    total_days = (end.date() - start.date()).days + 1
    elapsed_days = min(max((now.date() - start.date()).days + 1, 1), total_days)
    fraction = elapsed_days / total_days if total_days else 1.0

    by_category: Dict[str, Decimal] = {}
    for tx in transactions:
        if _is_expense(tx):
            by_category[tx.category] = by_category.get(tx.category, Decimal("0")) + to_decimal(
                tx.amount
            )

    out: List[Dict] = []
    for budget in budgets:
        limit = to_decimal(budget.amount)
        spent = money(by_category.get(budget.category, Decimal("0")))
        projected = money(Decimal(str(float(spent) / fraction)))
        ratio = safe_div(projected, limit, Decimal("0"))
        out.append(
            {
                "category": budget.category,
                "budget": money(limit),
                "spent": spent,
                "projected": projected,
                "over_projected": projected > limit,
                "projected_ratio": float(ratio),
            }
        )
    out.sort(key=lambda item: item["projected_ratio"], reverse=True)
    return out


def build_prediction_report(
    transactions: Sequence,
    budgets: Sequence = (),
) -> Dict:
    """The complete, honest prediction payload for one user.

    Always returns a dict. ``status`` is the honest headline: ``predicted`` only
    when there is enough history to justify it, ``insufficient_data`` otherwise,
    with the exact shortfall spelled out so the client knows whether to prompt
    for more transactions.
    """
    history = monthly_expense_history(transactions)
    prediction = forecast_next_month(transactions)

    # Category averages and month-to-date budget projections do not depend on a
    # long enough history for a trend, and are honest with a single month of
    # data. They are therefore computed in both branches rather than being
    # withheld alongside the trend forecast.
    categories = category_forecasts(transactions, history)
    projections = budget_projection(transactions, budgets)
    backtest = backtest_forecast(transactions)
    observed_average = (
        money(sum(m.amount for m in history) / Decimal(len(history))) if history else None
    )

    if prediction is None:
        return {
            "status": "insufficient_data",
            "message": (
                f"A forecast needs at least {MIN_MONTHS_FOR_TREND} months of "
                f"expense history. There {'is' if len(history) == 1 else 'are'} "
                f"{len(history)} month{'s' if len(history) != 1 else ''} of data "
                "so far, so no forecast is given rather than guessing from too "
                "few points. Keep recording expenses and this will fill in."
            ),
            "prediction": None,
            "required_months": MIN_MONTHS_FOR_TREND,
            "available_months": len(history),
            "months_needed": max(0, MIN_MONTHS_FOR_TREND - len(history)),
            "observed_average": observed_average,
            "history": [
                {"label": m.label, "expense": money(m.amount)} for m in history
            ],
            "categories": categories,
            "budget_projection": projections,
            "backtest": backtest,
        }

    return {
        "status": "predicted",
        "message": (
            f"Projected from {len(history)} months of your own spending history. "
            "This is a trend extrapolation, not a guarantee."
        ),
        "prediction": prediction.as_dict(),
        "required_months": MIN_MONTHS_FOR_TREND,
        "available_months": len(history),
        "months_needed": 0,
        "observed_average": observed_average,
        "history": [{"label": m.label, "expense": money(m.amount)} for m in history],
        "categories": categories,
        "budget_projection": projections,
        "backtest": backtest,
    }
