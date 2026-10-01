"""Financial assistant.

Two modes, and the response always states which one answered:

* ``builtin`` - a deterministic, fully local assistant. It answers from the
  user's own figures using intent matching, so it works with zero credentials
  and is unit-testable. It will say so when it does not understand a question.
* ``remote``  - forwards to a configured LLM provider, injecting a compact
  summary of the user's real data as grounding context.

There is no hard-coded response table pretending to be an AI. If the remote
provider is unreachable the request falls back to builtin and the response is
flagged ``fallback: true``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from app.core.config import settings
from app.services.analytics import (
    budget_progress,
    category_breakdown,
    generate_insights,
    monthly_series,
    totals,
)

logger = logging.getLogger(__name__)

CURRENCY = "INR "


def _fmt(value) -> str:
    try:
        return f"{CURRENCY}{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def build_context(transactions, budgets, alerts) -> Dict:
    """Compact, privacy-conscious summary of the user's finances."""
    t = totals(transactions)
    breakdown = category_breakdown(transactions)[:5]
    progress = budget_progress(budgets, transactions) if budgets else []
    months = monthly_series(transactions)

    return {
        "totals": {
            "income": str(t["income"]),
            "expense": str(t["expense"]),
            "net": str(t["net"]),
            "savings_rate_percent": t["savings_rate_percent"],
        },
        "top_categories": [{"category": c["category"], "amount": str(c["amount"]),
                            "percent": c["percent"]} for c in breakdown],
        "budget_progress": [
            {"category": p["category"], "limit": str(p["limit"]),
             "spent": str(p["spent"]), "used_percent": p["used_percent"],
             "status": p["status"]}
            for p in progress
        ],
        "monthly_trend": [{"period": m["label"], "expense": str(m["expense"]),
                           "income": str(m["income"])} for m in months[-6:]],
        "open_fraud_alerts": sum(1 for a in alerts if not a.is_dismissed) if alerts else 0,
        "transaction_count": len(transactions),
        "insights": [],
    }


def empty_context() -> Dict:
    """A well-formed context carrying no figures.

    Used when the caller opts out of grounding, so the intent engine still
    works and can explain what it *can* answer without leaking any amounts.
    """
    ctx = build_context([], [], [])
    ctx["insights"] = []
    return ctx


def context_summary_lines(ctx: Dict) -> List[str]:
    """Human-readable lines describing what was injected as context."""
    t = ctx["totals"]
    lines = [
        f"Income: {_fmt(t['income'])}, Expense: {_fmt(t['expense'])}, Net: {_fmt(t['net'])}",
        f"Savings rate: {t['savings_rate_percent']}%",
        f"Transactions analysed: {ctx['transaction_count']}",
    ]
    if ctx["top_categories"]:
        top = ", ".join(
            f"{c['category']} {_fmt(c['amount'])} ({c['percent']}%)"
            for c in ctx["top_categories"][:3]
        )
        lines.append(f"Top categories: {top}")
    if ctx["budget_progress"]:
        bp = ctx["budget_progress"][0]
        lines.append(
            f"Highest budget use: {bp['category']} at {bp['used_percent']}% ({bp['status']})"
        )
    return lines


# ---------------------------------------------------------------------------
# Builtin intent engine
# ---------------------------------------------------------------------------
INTENTS = (
    ("total_spending", ("total spend", "how much did i spend", "total expense", "spending total")),
    ("total_income", ("total income", "how much did i earn", "my income", "salary total")),
    ("net", ("net", "balance", "left over", "surplus", "deficit", "savings")),
    ("top_category", ("most", "largest", "biggest", "top category", "where did i spend")),
    ("budget", ("budget", "over budget", "budget status")),
    ("savings_rate", ("savings rate", "how much can i save", "save rate")),
    ("trend", ("trend", "month over month", "increasing", "decreasing", "this month")),
    ("fraud", ("fraud", "suspicious", "scam", "unauthorised", "unauthorized")),
    ("insights", ("insight", "advice", "suggest", "improve", "how can i")),
    ("help", ("what can you do", "help", "who are you", "capabilities")),
)


def _match_intent(message: str) -> str:
    lowered = (message or "").lower()
    for intent, phrases in INTENTS:
        if any(p in lowered for p in phrases):
            return intent
    return "unknown"


def answer_builtin(message: str, ctx: Dict) -> str:
    intent = _match_intent(message)
    t = ctx["totals"]

    if intent == "total_spending":
        return (
            f"Your total spending across {ctx['transaction_count']} transactions is "
            f"{_fmt(t['expense'])}."
        )
    if intent == "total_income":
        return f"Your total recorded income is {_fmt(t['income'])}."
    if intent == "net":
        direction = "saved" if float(t["net"]) >= 0 else "overspent by"
        return f"You have {direction} {_fmt(abs(float(t['net'])))} in this period."
    if intent == "savings_rate":
        return (
            f"Your savings rate is {t['savings_rate_percent']}%. "
            + (
                "That is healthy - consider directing part of it to a goal."
                if t["savings_rate_percent"] >= 20
                else "Aim for 20% or more by trimming your top discretionary category."
            )
        )
    if intent == "top_category":
        if not ctx["top_categories"]:
            return "I do not have enough categorised spending to tell you yet."
        c = ctx["top_categories"][0]
        return (
            f"Your biggest category is {c['category']} at {_fmt(c['amount'])}, "
            f"which is {c['percent']}% of your expenses."
        )
    if intent == "budget":
        if not ctx["budget_progress"]:
            return "You have not set any budgets for this period yet."
        lines = []
        for p in ctx["budget_progress"][:5]:
            lines.append(
                f"{p['category']}: {_fmt(p['spent'])} of {_fmt(p['limit'])} "
                f"({p['used_percent']}%) - {p['status']}"
            )
        return "Your budgets:\n" + "\n".join(lines)
    if intent == "trend":
        if len(ctx["monthly_trend"]) < 2:
            return "I need at least two months of data to show a trend."
        prev, curr = ctx["monthly_trend"][-2], ctx["monthly_trend"][-1]
        if float(prev["expense"]) > 0:
            pct = (float(curr["expense"]) - float(prev["expense"])) / float(prev["expense"]) * 100
            word = "up" if pct >= 0 else "down"
            return (
                f"Expenses are {word} {abs(pct):.1f}% - {curr['period']} was "
                f"{_fmt(curr['expense'])} versus {_fmt(prev['expense'])} in {prev['period']}."
            )
        return "I do not have a previous month to compare against."
    if intent == "fraud":
        n = ctx["open_fraud_alerts"]
        if n == 0:
            return "There are no open fraud alerts on your account."
        return (
            f"You have {n} open fraud alert(s). Review them in the Fraud section "
            "to confirm or dismiss each one."
        )
    if intent == "insights":
        insights = ctx.get("insights") or []
        if not insights:
            return "No notable insights yet - add a few more transactions."
        return "\n".join(f"- {i['title']}: {i['message']}" for i in insights[:4])
    if intent == "help":
        return (
            "I can tell you your total spending, income, net position, savings rate, "
            "top spending category, budget status, month-over-month trend, fraud alerts "
            "and overall insights. Ask in plain language."
        )
    return (
        "I did not recognise that question. I work from your own recorded figures, so "
        "try asking about total spending, income, savings rate, your top category, "
        "budget status, spending trend, or fraud alerts."
    )


def build_insight_context(transactions, budgets) -> List[Dict]:
    return generate_insights(transactions, budgets)


# ---------------------------------------------------------------------------
# Remote provider
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are the in-app financial assistant for Finance-AI. Answer only from the "
    "user context provided. Never invent transactions, amounts or dates. If the "
    "context does not contain the answer, say so plainly. Amounts are Indian "
    "rupees. Be concise and practical."
)


def _call_remote(message: str, ctx: Dict, history: Sequence) -> Optional[str]:
    if not settings.assistant_api_key:
        return None
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None

    base = (settings.assistant_base_url or "https://api.openai.com/v1").rstrip("/")
    system = SYSTEM_PROMPT + "\n\nUser financial context (JSON):\n" + _dumps(ctx)

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": message})

    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.assistant_api_key}"},
            json={"model": settings.assistant_model, "messages": messages, "temperature": 0.2},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("Assistant provider failed: %s", exc)
        return None


def _dumps(ctx: Dict) -> str:
    import json
    from datetime import datetime
    from decimal import Decimal

    def default(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    return json.dumps(ctx, default=default)


def respond(
    message: str,
    transactions,
    budgets,
    alerts,
    history: Sequence = (),
    include_context: bool = True,
) -> Dict:
    """Answer a user question about their finances."""
    if include_context:
        ctx = build_context(transactions, budgets, alerts)
        ctx["insights"] = build_insight_context(transactions, budgets)
    else:
        ctx = empty_context()
    used = context_summary_lines(ctx) if include_context else []

    suggestions = [
        "How much did I spend this period?",
        "Which category is my biggest expense?",
        "Am I close to any budget limit?",
        "How is my spending trending?",
        "Do I have any fraud alerts?",
    ]

    if settings.assistant_provider != "builtin" and settings.assistant_api_key:
        remote = _call_remote(message, ctx, history)
        if remote:
            return {
                "reply": remote,
                "provider": settings.assistant_provider,
                "model": settings.assistant_model,
                "context_used": used,
                "suggestions": suggestions,
                "fallback": False,
            }

    return {
        "reply": answer_builtin(message, ctx),
        "provider": "builtin",
        "model": None,
        "context_used": used,
        "suggestions": suggestions,
        "fallback": bool(settings.assistant_api_key),
    }
