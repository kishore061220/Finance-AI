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
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Sequence

from app.core.config import settings
from app.services.analytics import (
    budget_progress,
    category_breakdown,
    generate_insights,
    monthly_series,
    totals,
)
from app.utils.money import format_inr

logger = logging.getLogger(__name__)


def _fmt(value) -> str:
    """Format an amount for the assistant's own prose (e.g. ``₹1,23,456.78``)."""
    return format_inr(value)


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
# The remote model handles two kinds of question. General finance questions must
# work even for a brand-new account with no transactions, while questions about
# the user's own money must be grounded strictly in the injected context.
SYSTEM_PROMPT = (
    "You are the in-app financial assistant for Finance-AI. You answer two kinds "
    "of question.\n"
    "1) General financial education - budgeting and saving advice, ways to cut "
    "expenses, financial terminology, loans and EMIs, and hypothetical worked "
    "examples (for example 'my salary is X, suggest a budget'). Answer these "
    "from your own knowledge even when the user has no recorded transactions. "
    "Label any amounts in a hypothetical as illustrative examples, not the "
    "user's real figures, and never present them as guaranteed outcomes.\n"
    "2) The user's own finances - their actual spending, income, savings, top "
    "categories, budget progress, trends and fraud alerts. Answer these ONLY "
    "from the 'User financial context' below. Never invent transactions, "
    "amounts, dates or fraud alerts; if the context does not contain the "
    "answer, say so plainly.\n"
    "Amounts are in Indian rupees: write them with the rupee sign and Indian "
    "digit grouping (e.g. ₹1,23,456.78). When you split a requested total across "
    "categories, make the amounts add up exactly to that total and show the "
    "total. Clearly say which figures are illustrative versus taken from the "
    "user's account. Be concise and practical."
)

# The suggested prompts offered on the assistant page. Kept static so that
# rendering the page never triggers a (paid) remote call.
SUGGESTIONS = [
    "How much did I spend this period?",
    "Which category is my biggest expense?",
    "Am I close to any budget limit?",
    "How is my spending trending?",
    "Do I have any fraud alerts?",
]

# Only genuinely transient failures are retried in-request, with a bounded
# exponential backoff. Auth/validation errors (401/403/404/4xx) and timeouts are
# NOT retried, and a 429 is retried only when its Retry-After is short enough to
# actually wait for. A long 429 (daily quota) trips a cooldown instead.
TRANSIENT_STATUS = frozenset({500, 502, 503, 504})
RETRYABLE_STATUS = frozenset({429}) | TRANSIENT_STATUS  # retained for reference
MAX_REMOTE_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 4.0
REMOTE_TIMEOUT_SECONDS = 20.0

# Safe, provider-agnostic failure codes surfaced to the client. The raw provider
# body is never passed through.
ERROR_QUOTA_EXHAUSTED = "quota_exhausted"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_TIMEOUT = "timeout"
ERROR_AUTH = "auth_error"
ERROR_MODEL_NOT_FOUND = "model_not_found"
ERROR_BAD_RESPONSE = "bad_response"

# Codes the user may usefully retry straight away. Quota/auth/model errors are
# deliberately excluded: retrying them just wastes the budget or fails again.
RETRYABLE_ERROR_CODES = frozenset(
    {ERROR_PROVIDER_UNAVAILABLE, ERROR_TIMEOUT, ERROR_RATE_LIMITED}
)

# When the primary provider reports quota or unavailability we fall back to an
# optional secondary provider, but only if it is fully configured.
FALLBACK_TRIGGER_ERRORS = frozenset(
    {ERROR_QUOTA_EXHAUSTED, ERROR_PROVIDER_UNAVAILABLE, ERROR_TIMEOUT, ERROR_RATE_LIMITED}
)

# If a quota error carries no usable reset time, skip the provider for this long
# rather than hammering a known-dead endpoint on every request.
DEFAULT_QUOTA_COOLDOWN_SECONDS = 900.0

# Shown when the remote provider is configured but failed and the built-in
# engine has no data-backed answer for the question. It is deliberately honest
# rather than a plausible-looking canned reply.
REMOTE_UNAVAILABLE_REPLY = (
    "The remote financial assistant is temporarily unavailable, so I can't "
    "answer that question right now. Please try again in a moment."
)

QUOTA_REPLY_TEMPLATE = (
    "The Gemini daily quota is used up, so remote answers are paused for now. "
    "They should be available again around {when}."
)


# The last observed outcome of a remote attempt, so ``/config`` can report
# "working" vs "unavailable" from evidence rather than from configuration alone.
# ``None`` means "configured but never tried yet".
_remote_state: Optional[str] = None

# Circuit breaker: while a cooldown is active (set after a quota/long-429) the
# provider is skipped entirely so no quota is wasted; it auto-clears on expiry.
_cooldown_until_monotonic: Optional[float] = None
_cooldown_until_wall: Optional[datetime] = None
_cooldown_error: Optional[str] = None


@dataclass(frozen=True)
class _Provider:
    name: str
    base_url: str
    api_key: str
    model: str


class _Attempt(NamedTuple):
    content: Optional[str]
    error: Optional[str]
    retryable: bool
    retry_after: Optional[float]
    reason: str
    provider: Optional[str] = None
    model: Optional[str] = None


def _primary_provider() -> Optional[_Provider]:
    if not (settings.assistant_api_key and settings.assistant_provider != "builtin"):
        return None
    return _Provider(
        name=settings.assistant_provider,
        base_url=settings.assistant_base_url or "https://api.openai.com/v1",
        api_key=settings.assistant_api_key,
        model=settings.assistant_model,
    )


def _fallback_provider() -> Optional[_Provider]:
    """A secondary OpenAI-compatible provider, used only when fully configured."""
    base_url = getattr(settings, "fallback_llm_base_url", "")
    api_key = getattr(settings, "fallback_llm_api_key", "")
    model = getattr(settings, "fallback_llm_model", "")
    if base_url and api_key and model:
        return _Provider(name="fallback", base_url=base_url, api_key=api_key, model=model)
    return None


def _remote_configured() -> bool:
    return bool(settings.assistant_api_key and settings.assistant_provider != "builtin")


def _cooldown_seconds_remaining() -> Optional[float]:
    """Remaining cooldown in seconds, or ``None`` when no cooldown is active.

    Expired cooldowns are cleared lazily so the breaker auto-resets.
    """
    global _cooldown_until_monotonic, _cooldown_until_wall, _cooldown_error
    if _cooldown_until_monotonic is None:
        return None
    remaining = _cooldown_until_monotonic - time.monotonic()
    if remaining <= 0:
        _cooldown_until_monotonic = None
        _cooldown_until_wall = None
        _cooldown_error = None
        return None
    return remaining


def _start_cooldown(seconds: float, error: str) -> None:
    global _cooldown_until_monotonic, _cooldown_until_wall, _cooldown_error
    seconds = max(seconds, 1.0)
    _cooldown_until_monotonic = time.monotonic() + seconds
    _cooldown_until_wall = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    _cooldown_error = error


def cooldown_seconds_remaining() -> Optional[int]:
    """Whole seconds left on the circuit breaker, or ``None``."""
    remaining = _cooldown_seconds_remaining()
    return int(remaining) if remaining is not None else None


def cooldown_reset_at() -> Optional[str]:
    """ISO-8601 UTC time the breaker will clear, or ``None``."""
    if _cooldown_seconds_remaining() is None or _cooldown_until_wall is None:
        return None
    return _cooldown_until_wall.isoformat()


def cooldown_reset_label() -> Optional[str]:
    """Human-readable UTC time the breaker will clear, or ``None``."""
    if _cooldown_seconds_remaining() is None or _cooldown_until_wall is None:
        return None
    return _cooldown_until_wall.strftime("%d %b %Y, %H:%M UTC")


def remote_status() -> str:
    """One of ``builtin`` / ``configured`` / ``working`` / ``quota_exhausted`` /
    ``unavailable``.

    Configuration is not success: a key being present only makes the provider
    ``configured``. It becomes ``working`` after a real call succeeds and
    ``unavailable`` after one fails. Reporting "remote" merely because a key is
    set is exactly the bug this function exists to prevent.
    """
    if not _remote_configured():
        return "builtin"
    if _cooldown_seconds_remaining() is not None:
        return "quota_exhausted" if _cooldown_error == ERROR_QUOTA_EXHAUSTED else "unavailable"
    return _remote_state or "configured"


def reset_remote_state() -> None:
    """Clear the remembered remote outcome and any cooldown (tests; on reload)."""
    global _remote_state, _cooldown_until_monotonic, _cooldown_until_wall, _cooldown_error
    _remote_state = None
    _cooldown_until_monotonic = None
    _cooldown_until_wall = None
    _cooldown_error = None


def _extract_content(payload: Dict) -> str:
    """Pull the assistant text out of an OpenAI-compatible response body.

    Returns ``""`` (never raises) when the shape is unexpected or the content is
    missing/``null``/blank, so the caller can treat a 2xx-with-no-text as the
    failure it is rather than a success carrying an empty string.
    """
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(content, str):
        return ""
    return content.strip()


def _retry_after_seconds(response) -> Optional[float]:
    """Parse a provider's ``Retry-After`` header as seconds (unclamped)."""
    headers = getattr(response, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _parse_duration(text: str) -> Optional[float]:
    """Parse a Go/Google duration-ish string (``14h6m19.9s``) into seconds."""
    if not text:
        return None
    total = 0.0
    found = False
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text):
        found = True
        total += float(value) * {"h": 3600.0, "m": 60.0, "s": 1.0}[unit]
    return total if found else None


def _provider_error_object(response):
    """Best-effort extraction of the ``error`` object from a provider body.

    OpenAI-compatible endpoints nest it at ``error``; Gemini sometimes wraps it
    in a single-element list. Returns ``{}`` when nothing recognisable is found.
    """
    try:
        payload = response.json()
    except Exception:
        return {}
    err = None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        err = payload[0].get("error")
    elif isinstance(payload, dict):
        err = payload.get("error")
        if err is None and ("status" in payload or "message" in payload):
            err = payload
    return err if isinstance(err, dict) else {}


def _provider_error_fields(response):
    """Best-effort ``(status_string, message, error_object)`` from a body."""
    err = _provider_error_object(response)
    status = err.get("status") if isinstance(err.get("status"), str) else None
    message = err.get("message") if isinstance(err.get("message"), str) else ""
    return status, message, err


def _looks_like_quota(status: Optional[str], message: str) -> bool:
    if status and "RESOURCE_EXHAUSTED" in status.upper():
        return True
    return "quota" in (message or "").lower()


def _quota_retry_seconds(response, header_retry: Optional[float]) -> Optional[float]:
    """Reset delay for a quota error, from the header, RetryInfo, or message."""
    if header_retry is not None:
        return header_retry
    _, message, err = _provider_error_fields(response)
    for detail in err.get("details") or []:
        if isinstance(detail, dict) and detail.get("retryDelay"):
            parsed = _parse_duration(str(detail["retryDelay"]))
            if parsed is not None:
                return parsed
    match = re.search(r"retry in ([0-9hms\.]+)", message, re.IGNORECASE)
    if match:
        return _parse_duration(match.group(1))
    return None


def _classify_response(response) -> _Attempt:
    """Map a provider response to a safe error code (or accepted content)."""
    code = response.status_code
    if code in (401, 403):
        return _Attempt(None, ERROR_AUTH, False, None, f"HTTP {code}")
    if code == 404:
        return _Attempt(None, ERROR_MODEL_NOT_FOUND, False, None, f"HTTP {code}")
    if code == 429:
        status, message, _ = _provider_error_fields(response)
        header_retry = _retry_after_seconds(response)
        if _looks_like_quota(status, message):
            secs = _quota_retry_seconds(response, header_retry)
            return _Attempt(None, ERROR_QUOTA_EXHAUSTED, False, secs, "HTTP 429 quota")
        retryable = header_retry is not None and header_retry <= MAX_BACKOFF_SECONDS
        return _Attempt(None, ERROR_RATE_LIMITED, retryable, header_retry, "HTTP 429")
    if code in TRANSIENT_STATUS:
        return _Attempt(None, ERROR_PROVIDER_UNAVAILABLE, True, _retry_after_seconds(response), f"HTTP {code}")
    if code >= 500:
        return _Attempt(None, ERROR_PROVIDER_UNAVAILABLE, True, _retry_after_seconds(response), f"HTTP {code}")
    if code >= 400:
        # Remaining 4xx (400/422...) are request problems, not transient.
        return _Attempt(None, ERROR_BAD_RESPONSE, False, None, f"HTTP {code}")
    try:
        payload = response.json()
    except Exception:
        return _Attempt(None, ERROR_BAD_RESPONSE, False, None, "unparseable body")
    content = _extract_content(payload)
    if not content:
        # A 2xx with blank/whitespace/null/malformed content is a failed answer,
        # not a success: accepting it would let ``respond`` fall back to builtin
        # while reporting the remote model as "working".
        return _Attempt(None, ERROR_BAD_RESPONSE, False, None, "empty reply")
    return _Attempt(content, None, False, None, "ok")


def _attempt_remote(httpx, url: str, headers: Dict, body: Dict) -> _Attempt:
    """One provider call, classified into a safe :class:`_Attempt`."""
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=REMOTE_TIMEOUT_SECONDS)
    except Exception as exc:  # httpx transport/timeout errors, or anything else
        name = type(exc).__name__
        if isinstance(exc, httpx.TimeoutException):
            return _Attempt(None, ERROR_TIMEOUT, False, None, name)
        return _Attempt(None, ERROR_PROVIDER_UNAVAILABLE, False, None, name)
    return _classify_response(response)


def _call_provider(httpx, provider: _Provider, message: str, ctx: Dict, history: Sequence) -> _Attempt:
    base = provider.base_url.rstrip("/")
    system = SYSTEM_PROMPT + "\n\nUser financial context (JSON):\n" + _dumps(ctx)

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": message})

    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {provider.api_key}"}
    body = {"model": provider.model, "messages": messages, "temperature": 0.2}

    last = _Attempt(None, ERROR_PROVIDER_UNAVAILABLE, False, None, "no attempt",
                    provider.name, provider.model)
    for attempt in range(1, MAX_REMOTE_ATTEMPTS + 1):
        result = _attempt_remote(httpx, url, headers, body)._replace(
            provider=provider.name, model=provider.model
        )
        if result.content:
            return result
        last = result
        if not result.retryable or attempt == MAX_REMOTE_ATTEMPTS:
            logger.warning(
                "Assistant provider '%s' failed (%s) after %d attempt(s)",
                provider.name, result.reason, attempt,
            )
            break
        delay = result.retry_after if result.retry_after is not None else BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
        delay = min(delay, MAX_BACKOFF_SECONDS)
        logger.info(
            "Assistant provider '%s' transient failure (%s); retrying in %.2fs",
            provider.name, result.reason, delay,
        )
        if delay > 0:
            time.sleep(delay)
    return last


def _call_remote(message: str, ctx: Dict, history: Sequence) -> _Attempt:
    global _remote_state
    try:
        import httpx
    except ImportError:  # pragma: no cover
        _remote_state = "unavailable"
        return _Attempt(None, ERROR_PROVIDER_UNAVAILABLE, False, None, "httpx missing")

    primary = _primary_provider()
    if primary is None:  # pragma: no cover - guarded by the caller
        return _Attempt(None, ERROR_AUTH, False, None, "unconfigured")

    result = _call_provider(httpx, primary, message, ctx, history)
    if result.content:
        _remote_state = "working"
        return result

    # Primary failed. Use the optional secondary provider only for quota or
    # unavailability, and only when it is fully configured.
    if result.error in FALLBACK_TRIGGER_ERRORS:
        fallback = _fallback_provider()
        if fallback is not None:
            logger.info("Assistant falling back to the secondary provider")
            fb_result = _call_provider(httpx, fallback, message, ctx, history)
            if fb_result.content:
                _remote_state = "working"
                return fb_result
            result = fb_result

    _remote_state = "unavailable"
    return result


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


def _builtin_is_meaningful(message: str, ctx: Dict) -> bool:
    """Whether the built-in engine can answer this from real account data.

    A no-data account would otherwise get a hollow "₹0.00" reply to a personal
    question and an unrelated canned line to a general one. When the provider is
    down we prefer to admit that and offer a retry instead of guessing.
    """
    intent = _match_intent(message)
    if intent in {"total_spending", "total_income", "net", "top_category",
                  "savings_rate", "trend"}:
        return ctx["transaction_count"] > 0
    if intent == "budget":
        return bool(ctx["budget_progress"])
    if intent == "fraud":
        return True  # "no open alerts" is a real answer, not invented data
    if intent == "insights":
        return bool(ctx.get("insights"))
    return False


def _quota_reply(when: Optional[str]) -> str:
    if when:
        return QUOTA_REPLY_TEMPLATE.format(when=when)
    return REMOTE_UNAVAILABLE_REPLY


def _fallback_response(
    message: str,
    ctx: Dict,
    used: List[str],
    suggestions: List[str],
    error_code: str,
    retry_after_seconds: Optional[int],
    retryable: bool,
) -> Dict:
    """A built-in/None answer for a failed remote call, with an honest code.

    The built-in engine answers only when it can ground the reply in the user's
    real data; otherwise we say plainly that the remote is unavailable (or which
    error stopped it) instead of returning an unrelated canned reply.
    """
    if _builtin_is_meaningful(message, ctx):
        reply = answer_builtin(message, ctx)
    elif error_code == ERROR_QUOTA_EXHAUSTED:
        reply = _quota_reply(cooldown_reset_label())
    else:
        reply = REMOTE_UNAVAILABLE_REPLY
    return {
        "reply": reply,
        "provider": "builtin",
        "model": None,
        "context_used": used,
        "suggestions": suggestions,
        "fallback": True,
        "retryable": retryable,
        "error": error_code,
        "retry_after_seconds": retry_after_seconds,
    }


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
    suggestions = list(SUGGESTIONS)

    if _remote_configured():
        # Circuit breaker: if a quota/long-429 cooldown is active, do not touch
        # the provider at all - answer instantly from what we already know.
        remaining = cooldown_seconds_remaining()
        if remaining is not None:
            error_code = _cooldown_error or ERROR_PROVIDER_UNAVAILABLE
            return _fallback_response(
                message, ctx, used, suggestions, error_code, remaining, False
            )

        remote = _call_remote(message, ctx, history)
        if remote.content:
            return {
                "reply": remote.content,
                "provider": remote.provider or settings.assistant_provider,
                "model": remote.model or settings.assistant_model,
                "context_used": used,
                "suggestions": suggestions,
                "fallback": False,
                "retryable": False,
                "error": None,
                "retry_after_seconds": None,
            }

        error_code = remote.error or ERROR_PROVIDER_UNAVAILABLE
        retry_after = remote.retry_after
        # Open the breaker on quota, or on a 429 the provider asked us to wait
        # out beyond our in-request budget.
        if error_code == ERROR_QUOTA_EXHAUSTED:
            _start_cooldown(retry_after or DEFAULT_QUOTA_COOLDOWN_SECONDS, error_code)
        elif (
            error_code == ERROR_RATE_LIMITED
            and retry_after is not None
            and retry_after > MAX_BACKOFF_SECONDS
        ):
            _start_cooldown(retry_after, error_code)

        remaining = cooldown_seconds_remaining()
        if remaining is not None:
            retry_after = remaining
        retryable = error_code in RETRYABLE_ERROR_CODES and remaining is None
        return _fallback_response(
            message, ctx, used, suggestions, error_code, retry_after, retryable
        )

    return {
        "reply": answer_builtin(message, ctx),
        "provider": "builtin",
        "model": None,
        "context_used": used,
        "suggestions": suggestions,
        "fallback": False,
        "retryable": False,
        "error": None,
        "retry_after_seconds": None,
    }
