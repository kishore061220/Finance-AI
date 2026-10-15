"""Tests for the financial assistant.

Two things are being pinned down here:

* the built-in engine answers from the caller's own figures, in INR, and never
  pretends the remote model is in use when it is not;
* the remote provider is used only when configured, its failure is visible
  (``fallback: true``), and the reported status distinguishes "configured" from
  "actually working".
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.routes import assistant as assistant_routes
from app.services import assistant
from app.services.ratelimit import FixedWindowLimiter


def _settings(**overrides) -> Settings:
    base = {
        "secret_key": "test-secret-key-not-for-production",
        "allow_dev_auth": True,
        "app_env": "test",
        "assistant_provider": "builtin",
        "assistant_api_key": "",
        "assistant_model": "gpt-4o-mini",
        "assistant_base_url": "",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _reset_remote_state(monkeypatch):
    # Retries must not sleep during the suite.
    monkeypatch.setattr(assistant, "BASE_BACKOFF_SECONDS", 0.0)
    assistant.reset_remote_state()
    yield
    assistant.reset_remote_state()


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


def _remote_settings(**overrides) -> Settings:
    return _settings(
        assistant_provider="openai",
        assistant_api_key="secret-key",
        **overrides,
    )


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr(assistant, "settings", settings)
    monkeypatch.setattr(assistant_routes, "settings", settings)


def _quota_response(reset_seconds: int = 50400) -> _FakeResponse:
    """A real-shaped Gemini free-tier quota error (body-only reset time)."""
    body = [
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": (
                    "You exceeded your current quota ... retry in 14h0m0s."
                ),
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                     "retryDelay": f"{reset_seconds}s"}
                ],
            }
        }
    ]
    return _FakeResponse(body, status_code=429)


def _counted_post(monkeypatch, produce):
    """Install a fake ``httpx.post`` that counts calls and calls ``produce(i)``."""
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return produce(calls["n"] - 1)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# ---------------------------------------------------------------------------
# Built-in engine
# ---------------------------------------------------------------------------
class TestBuiltinAnswers:
    def test_amounts_use_the_rupee_symbol_and_indian_grouping(self):
        ctx = assistant.empty_context()
        ctx["totals"] = {
            "income": "100000",
            "expense": "123456.78",
            "net": "-23456.78",
            "savings_rate_percent": 10,
        }
        ctx["transaction_count"] = 5

        reply = assistant.answer_builtin("total spending", ctx)
        assert "₹1,23,456.78" in reply

    def test_context_summary_lines_carry_no_western_grouping(self):
        ctx = assistant.empty_context()
        ctx["totals"] = {
            "income": "100000",
            "expense": "0",
            "net": "100000",
            "savings_rate_percent": 100,
        }
        lines = assistant.context_summary_lines(ctx)
        assert any("₹1,00,000.00" in line for line in lines)
        assert not any("1,000,000" in line for line in lines)

    def test_unknown_question_admits_it_does_not_know(self):
        reply = assistant.answer_builtin("what is the meaning of life", assistant.empty_context())
        assert "did not recognise" in reply


class TestProviderSelection:
    def test_builtin_is_used_when_not_configured(self, monkeypatch):
        _patch_settings(monkeypatch, _settings())
        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is False

    def test_remote_is_used_when_configured_and_reachable(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        captured: dict = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, json=json, timeout=timeout)
            return _FakeResponse(
                {"choices": [{"message": {"content": "  You spent ₹3,00,000.00.  "}}]}
            )

        monkeypatch.setattr(httpx, "post", fake_post)

        out = assistant.respond("how much did i spend", [], [], [])
        assert out["provider"] == "openai"
        assert out["model"] == "gpt-4o-mini"
        assert out["fallback"] is False
        assert out["reply"] == "You spent ₹3,00,000.00."  # trimmed
        assert captured["headers"]["Authorization"] == "Bearer secret-key"
        assert captured["timeout"] == 20.0
        assert captured["url"].endswith("/chat/completions")

    def test_remote_failure_falls_back_and_is_flagged(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        def boom(*args, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "post", boom)

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True

    def test_remote_non_2xx_falls_back(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=500))

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True

    def test_blank_remote_reply_falls_back_and_is_not_reported_working(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        # A 2xx whose content is blank is NOT an answer: the user is shown the
        # builtin reply, so the provider must not be reported as "working".
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content": "   "}}]}
            )
        )

        out = assistant.respond("suggest a budget", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert assistant.remote_status() == "unavailable"

    def test_null_remote_content_falls_back(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content": None}}]}
            )
        )

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert assistant.remote_status() == "unavailable"

    def test_malformed_provider_body_falls_back(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"unexpected": True}))

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert assistant.remote_status() == "unavailable"


class TestProviderRetries:
    def _fake(self, monkeypatch, responses):
        calls = {"n": 0}

        def fake_post(url, headers=None, json=None, timeout=None):
            i = min(calls["n"], len(responses) - 1)
            calls["n"] += 1
            return responses[i]

        monkeypatch.setattr(httpx, "post", fake_post)
        return calls

    @staticmethod
    def _ok(text: str = "hello"):
        return _FakeResponse({"choices": [{"message": {"content": text}}]})

    def test_503_then_success_is_retried_and_used(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = self._fake(
            monkeypatch, [_FakeResponse({}, status_code=503), self._ok("recovered")]
        )

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "openai"
        assert out["reply"] == "recovered"
        assert out["fallback"] is False
        assert out["retryable"] is False
        assert assistant.remote_status() == "working"
        assert calls["n"] == 2

    def test_persistent_503_stops_at_the_retry_limit(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = self._fake(monkeypatch, [_FakeResponse({}, status_code=503)])

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert out["retryable"] is True
        assert calls["n"] == assistant.MAX_REMOTE_ATTEMPTS
        assert assistant.remote_status() == "unavailable"

    def test_authentication_error_is_not_retried(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = self._fake(monkeypatch, [_FakeResponse({}, status_code=401)])

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert calls["n"] == 1

    def test_validation_error_is_not_retried(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = self._fake(monkeypatch, [_FakeResponse({}, status_code=400)])

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert calls["n"] == 1

    def test_timeout_is_not_retried(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise httpx.ReadTimeout("slow provider")

        monkeypatch.setattr(httpx, "post", boom)

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert calls["n"] == 1

    def test_retry_after_header_is_honoured(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        class _RetryResponse(_FakeResponse):
            headers = {"Retry-After": "0"}

        seq = [_RetryResponse({}, status_code=503), self._ok("ok")]
        calls = self._fake(monkeypatch, seq)

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "openai"
        assert calls["n"] == 2

    def test_a_retry_after_longer_than_our_budget_is_not_retried(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        class _LongRetryResponse(_FakeResponse):
            headers = {"Retry-After": "3600"}

        calls = self._fake(
            monkeypatch, [_LongRetryResponse({}, status_code=429), self._ok("never")]
        )

        out = assistant.respond("total income", [], [], [])
        assert out["provider"] == "builtin"
        assert out["error"] == assistant.ERROR_RATE_LIMITED
        # The provider asked for an hour; we must not busy-retry within the call.
        assert calls["n"] == 1
        # A long 429 opens the breaker, so a retry now would only waste budget.
        assert out["retryable"] is False
        assert assistant.remote_status() == "unavailable"
        assert assistant.cooldown_seconds_remaining() is not None


class TestGeneralVersusPersonal:
    def test_general_salary_budget_is_answered_remotely_without_transactions(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content":
                    "Illustrative ₹15,000 budget: food ₹5,000, transport ₹2,000, "
                    "personal ₹3,000, savings ₹5,000. Total ₹15,000."}}]}
            )
        )

        out = assistant.respond(_CUSTOM_BUDGET_QUESTION, [], [], [])
        assert out["provider"] == "openai"
        assert out["fallback"] is False
        assert "₹15,000" in out["reply"]

    def test_general_question_when_provider_down_does_not_fake_an_answer(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=503))

        out = assistant.respond("Explain how EMIs work", [], [], [])
        assert out["provider"] == "builtin"
        assert out["fallback"] is True
        assert out["retryable"] is True
        assert out["reply"] == assistant.REMOTE_UNAVAILABLE_REPLY


_CUSTOM_BUDGET_QUESTION = (
    "My monthly salary is \u20b915,000. Suggest a budget for food, transport, "
    "personal expenses, and savings. Give each category an amount and ensure "
    "the total is exactly \u20b915,000."
)


class TestProviderErrorCodes:
    """Each real failure is mapped to a safe code and the right retry policy."""

    def _one(self, monkeypatch, response):
        _patch_settings(monkeypatch, _remote_settings())
        return _counted_post(monkeypatch, lambda i: response)

    def test_quota_exhausted_is_classified_with_reset_and_not_retried(self, monkeypatch):
        calls = self._one(monkeypatch, _quota_response(50400))
        out = assistant.respond("hi", [], [], [])
        assert out["provider"] == "builtin"
        assert out["error"] == assistant.ERROR_QUOTA_EXHAUSTED
        assert out["retryable"] is False
        assert 50000 < out["retry_after_seconds"] <= 50400
        # A quota rejection must not be retried in-request.
        assert calls["n"] == 1

    def test_auth_error_is_classified_and_not_retried(self, monkeypatch):
        calls = self._one(monkeypatch, _FakeResponse({}, status_code=401))
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_AUTH
        assert out["retryable"] is False
        assert calls["n"] == 1

    def test_forbidden_is_classified_as_auth_error(self, monkeypatch):
        calls = self._one(monkeypatch, _FakeResponse({}, status_code=403))
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_AUTH
        assert calls["n"] == 1

    def test_model_not_found_is_classified(self, monkeypatch):
        calls = self._one(monkeypatch, _FakeResponse({}, status_code=404))
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_MODEL_NOT_FOUND
        assert out["retryable"] is False
        assert calls["n"] == 1

    def test_timeout_is_classified_as_timeout(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        def boom(*a, **k):
            raise httpx.ReadTimeout("slow")

        monkeypatch.setattr(httpx, "post", boom)
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_TIMEOUT
        # A timeout is optionally retryable by the user, but not auto-retried.
        assert out["retryable"] is True

    def test_5xx_is_provider_unavailable_and_is_retried(self, monkeypatch):
        calls = self._one(monkeypatch, _FakeResponse({}, status_code=503))
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_PROVIDER_UNAVAILABLE
        assert out["retryable"] is True
        assert calls["n"] == assistant.MAX_REMOTE_ATTEMPTS

    def test_blank_2xx_is_a_bad_response(self, monkeypatch):
        calls = self._one(
            monkeypatch, _FakeResponse({"choices": [{"message": {"content": "  "}}]})
        )
        out = assistant.respond("hi", [], [], [])
        assert out["error"] == assistant.ERROR_BAD_RESPONSE
        assert out["retryable"] is False
        assert calls["n"] == 1


class TestQuotaCircuitBreaker:
    def test_breaker_skips_the_provider_until_reset(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = _counted_post(monkeypatch, lambda i: _quota_response(3600))

        first = assistant.respond("hi", [], [], [])
        assert first["error"] == assistant.ERROR_QUOTA_EXHAUSTED
        made = calls["n"]

        second = assistant.respond("how much did i spend", [], [], [])
        # No new provider call was attempted while the breaker is open.
        assert calls["n"] == made
        assert second["error"] == assistant.ERROR_QUOTA_EXHAUSTED
        assert second["fallback"] is True
        assert assistant.remote_status() == "quota_exhausted"

    def test_breaker_auto_clears_after_the_reset(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        _counted_post(monkeypatch, lambda i: _quota_response(3600))

        assistant.respond("hi", [], [], [])
        assert assistant.cooldown_seconds_remaining() is not None

        real = assistant.time.monotonic
        monkeypatch.setattr(assistant.time, "monotonic", lambda: real() + 10 ** 9)
        assert assistant.cooldown_seconds_remaining() is None
        assert assistant.remote_status() != "quota_exhausted"

    def test_a_general_question_while_the_breaker_is_open_states_the_quota(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        _counted_post(monkeypatch, lambda i: _quota_response(3600))

        assistant.respond("hi", [], [], [])
        out = assistant.respond("Explain how EMIs work", [], [], [])
        assert out["provider"] == "builtin"
        assert out["error"] == assistant.ERROR_QUOTA_EXHAUSTED
        assert out["retryable"] is False
        assert "quota" in out["reply"].lower()


class TestAttemptCountsAndGeneralQuestions:
    def test_one_message_makes_exactly_one_call_when_healthy(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        calls = _counted_post(
            monkeypatch,
            lambda i: _FakeResponse({"choices": [{"message": {"content": "answer"}}]}),
        )
        out = assistant.respond("hi", [], [], [])
        assert out["provider"] == "openai"
        assert out["fallback"] is False
        assert calls["n"] == 1

    def test_the_exact_typed_text_is_what_the_provider_receives(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        captured: dict = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(json=json)
            return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr(httpx, "post", fake_post)
        assistant.respond("hi", [], [], [])
        assert captured["json"]["messages"][-1] == {"role": "user", "content": "hi"}

    def test_a_general_budget_question_is_answered_remotely_without_transactions(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content":
                    "Illustrative \u20b915,000 budget: food \u20b95,000, transport "
                    "\u20b92,000, personal \u20b93,000, savings \u20b95,000."}}]}
            )
        )
        out = assistant.respond(
            "My monthly salary is \u20b915,000. Suggest a budget for food, "
            "transport, personal expenses, and savings so the total is \u20b915,000.",
            [], [], [],
        )
        assert out["provider"] == "openai"
        assert out["fallback"] is False
        assert "\u20b915,000" in out["reply"]


class TestTypedVersusSuggestedQuestions:
    """A typed question must reach the remote model exactly like a suggested one.

    Typed questions are the ones that regressed: the remote call was made, but a
    blank 2xx was recorded as success, so the reply silently came from the
    builtin engine while ``/config`` claimed the remote had answered.
    """

    def _remote_echoing(self, monkeypatch, reply: str):
        captured: dict = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(json=json)
            return _FakeResponse({"choices": [{"message": {"content": reply}}]})

        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", fake_post)
        return captured

    def test_a_typed_question_is_forwarded_verbatim_and_answered_remotely(self, monkeypatch):
        from app.schemas.common import AssistantMessage

        captured = self._remote_echoing(monkeypatch, "Here is a \u20b915,000 budget...")
        history = [
            AssistantMessage(role="user", content="How much did I spend?"),
            AssistantMessage(role="assistant", content="\u20b90.00"),
        ]

        out = assistant.respond(_CUSTOM_BUDGET_QUESTION, [], [], [], history=history)

        # The exact typed text is the final user message sent upstream...
        assert captured["json"]["messages"][-1] == {
            "role": "user",
            "content": _CUSTOM_BUDGET_QUESTION,
        }
        # ...and the remote answer (not a builtin one) is what the user sees.
        assert out["provider"] == "openai"
        assert out["fallback"] is False
        assert out["reply"] == "Here is a \u20b915,000 budget..."
        assert assistant.remote_status() == "working"

    def test_suggested_and_typed_questions_take_the_same_path(self, monkeypatch):
        captured = self._remote_echoing(monkeypatch, "ok")

        assistant.respond("How much did I spend this period?", [], [], [])
        suggested = captured["json"]["messages"][-1]["content"]

        assistant.respond(_CUSTOM_BUDGET_QUESTION, [], [], [])
        typed = captured["json"]["messages"][-1]["content"]

        assert suggested == "How much did I spend this period?"
        assert typed == _CUSTOM_BUDGET_QUESTION


class TestRemoteStatus:
    def test_unconfigured_reports_builtin(self, monkeypatch):
        _patch_settings(monkeypatch, _settings())
        assert assistant.remote_status() == "builtin"

    def test_configured_but_untried_is_not_claimed_as_working(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        assert assistant.remote_status() == "configured"

    def test_success_then_failure_moves_working_to_unavailable(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())

        monkeypatch.setattr(
            httpx,
            "post",
            lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content": "ok"}}]}
            ),
        )
        assistant.respond("hi", [], [], [])
        assert assistant.remote_status() == "working"

        def boom(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "post", boom)
        assistant.respond("hi", [], [], [])
        assert assistant.remote_status() == "unavailable"


# ---------------------------------------------------------------------------
# Route level
# ---------------------------------------------------------------------------
def _seed_transaction(db, user_id: int, amount: str, *, income: bool = False) -> None:
    from app.models.transaction import Transaction, TransactionType

    db.add(
        Transaction(
            user_id=user_id,
            transaction_type=TransactionType.INCOME if income else TransactionType.EXPENSE,
            amount=Decimal(amount),
            category="Salary" if income else "Food",
            transaction_date=datetime.utcnow().replace(microsecond=0),
        )
    )
    db.commit()


class TestAssistantRoute:
    def test_context_is_only_the_callers_own_data(self, client, auth, other_auth, db):
        alice = client.get("/api/auth/me", headers=auth).json()["id"]
        bob = client.get("/api/auth/me", headers=other_auth).json()["id"]
        _seed_transaction(db, alice, "123456.78")
        _seed_transaction(db, bob, "999999.99")

        response = client.post(
            "/api/assistant", headers=auth, json={"message": "total spending"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "builtin"
        assert "₹1,23,456.78" in body["reply"]
        # Bob's spending must never appear in Alice's answer or context.
        assert "9,99,999.99" not in response.text
        assert not any("9,99,999" in line for line in body["context_used"])

    def test_requires_authentication(self, client):
        assert client.post("/api/assistant", json={"message": "hi"}).status_code == 401

    def test_rejects_an_empty_message(self, client, auth):
        assert client.post(
            "/api/assistant", headers=auth, json={"message": ""}
        ).status_code == 422

    def test_rejects_a_whitespace_only_message(self, client, auth):
        assert client.post(
            "/api/assistant", headers=auth, json={"message": "   "}
        ).status_code == 422

    def test_personal_question_falls_back_to_real_data_when_provider_down(
        self, client, auth, db, monkeypatch
    ):
        alice = client.get("/api/auth/me", headers=auth).json()["id"]
        _seed_transaction(db, alice, "123456.78")
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=503))

        body = client.post(
            "/api/assistant", headers=auth, json={"message": "total spending"}
        ).json()
        # The provider failed, but the built-in engine answers from real data
        # and the reply is clearly marked as a retryable fallback.
        assert body["provider"] == "builtin"
        assert body["fallback"] is True
        assert body["retryable"] is True
        assert "₹1,23,456.78" in body["reply"]

    def test_general_question_when_provider_down_is_not_faked(
        self, client, auth, monkeypatch
    ):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=503))

        body = client.post(
            "/api/assistant",
            headers=auth,
            json={"message": "Explain how an EMI is calculated"},
        ).json()
        assert body["provider"] == "builtin"
        assert body["fallback"] is True
        assert body["retryable"] is True
        assert body["reply"] == assistant.REMOTE_UNAVAILABLE_REPLY

    def test_rejects_an_overlong_history(self, client, auth):
        history = [{"role": "user", "content": "x" * 10} for _ in range(50)]
        response = client.post(
            "/api/assistant",
            headers=auth,
            json={"message": "hi", "history": history},
        )
        assert response.status_code == 422

    def test_rate_limit_returns_429(self, client, auth, monkeypatch):
        from app.services import ratelimit

        monkeypatch.setattr(ratelimit.assistant_limiter, "max_requests", 1)
        ratelimit.assistant_limiter.reset()

        first = client.post("/api/assistant", headers=auth, json={"message": "hi"})
        assert first.status_code == 200

        second = client.post("/api/assistant", headers=auth, json={"message": "hi"})
        assert second.status_code == 429


class TestAssistantConfigRoute:
    def test_builtin_by_default(self, client, auth):
        body = client.get("/api/assistant/config", headers=auth).json()
        assert body["provider"] == "builtin"
        assert body["remote_configured"] is False
        assert body["status"] == "builtin"
        assert "built-in" in body["message"]

    def test_configured_remote_is_not_reported_as_working(self, client, auth, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings(assistant_model="gpt-4o"))

        body = client.get("/api/assistant/config", headers=auth).json()
        assert body["remote_configured"] is True
        assert body["model"] == "gpt-4o"
        # Configured, but no call has succeeded yet.
        assert body["status"] == "configured"

    def test_suggestions_are_static_and_never_trigger_a_remote_call(
        self, client, auth, monkeypatch
    ):
        _patch_settings(monkeypatch, _remote_settings())
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise AssertionError("config must not call the provider")

        monkeypatch.setattr(httpx, "post", boom)

        body = client.get("/api/assistant/config", headers=auth).json()
        assert body["suggestions"] == list(assistant.SUGGESTIONS)
        assert calls["n"] == 0

    def test_quota_exhausted_status_is_surfaced_truthfully(self, client, auth, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _quota_response(50400))

        # A rejected ask opens the breaker...
        client.post("/api/assistant", headers=auth, json={"message": "hi"})

        body = client.get("/api/assistant/config", headers=auth).json()
        assert body["status"] == "quota_exhausted"
        assert body["retry_after_seconds"] and body["retry_after_seconds"] > 0
        assert "quota" in body["message"].lower()


class TestOptionalFallbackProvider:
    """A secondary provider is used only when fully configured and needed."""

    def test_absent_by_default(self, monkeypatch):
        _patch_settings(monkeypatch, _remote_settings())
        assert assistant._fallback_provider() is None

    def test_used_when_the_primary_is_quota_exhausted(self, monkeypatch):
        _patch_settings(
            monkeypatch,
            _remote_settings(
                fallback_llm_base_url="https://fallback.example/v1",
                fallback_llm_api_key="fb-key",
                fallback_llm_model="fb-model",
            ),
        )

        def fake_post(url, headers=None, json=None, timeout=None):
            if "fallback.example" in url:
                return _FakeResponse(
                    {"choices": [{"message": {"content": "answered by fallback"}}]}
                )
            return _quota_response(3600)

        monkeypatch.setattr(httpx, "post", fake_post)
        out = assistant.respond("hi", [], [], [])
        assert out["provider"] == "fallback"
        assert out["model"] == "fb-model"
        assert out["reply"] == "answered by fallback"


class TestFixedWindowLimiter:
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = FixedWindowLimiter(max_requests=2, window_seconds=10)
        assert limiter.allow("u", now=0.0) is True
        assert limiter.allow("u", now=1.0) is True
        assert limiter.allow("u", now=2.0) is False

    def test_the_window_slides(self):
        limiter = FixedWindowLimiter(max_requests=2, window_seconds=10)
        assert limiter.allow("u", now=0.0) is True
        assert limiter.allow("u", now=1.0) is True
        assert limiter.allow("u", now=2.0) is False
        # The first hit has aged out by t=11.
        assert limiter.allow("u", now=11.0) is True

    def test_keys_are_independent(self):
        limiter = FixedWindowLimiter(max_requests=1, window_seconds=10)
        assert limiter.allow("alice", now=0.0) is True
        assert limiter.allow("bob", now=0.0) is True
        assert limiter.allow("alice", now=1.0) is False
