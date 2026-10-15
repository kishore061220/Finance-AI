"""Assistant routes.

The assistant answers from the caller's own data. The response always declares
which engine replied and, when the configured LLM provider is unavailable, that
it fell back to the built-in engine.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.budget import Budget
from app.models.fraud_alert import FraudAlert
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import AssistantRequest, AssistantResponse
from app.services import assistant
from app.services.ratelimit import assistant_limiter

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Configuration alone never claims the remote model is working. ``status`` is
# derived from the last real attempt and any active circuit breaker
# (see assistant.remote_status):
#   builtin          - not configured; the rule engine answers
#   configured       - a key is set but no call has been made yet
#   working          - the last remote call succeeded
#   quota_exhausted  - the provider's quota is spent (breaker open until reset)
#   unavailable      - the last remote call failed; answers fell back to builtin
_STATUS_MESSAGES = {
    "builtin": "The assistant is using the built-in engine.",
    "configured": "The remote model is configured and ready.",
    "working": "The remote model answered the last request successfully.",
    "quota_exhausted": "The Gemini daily quota is used up.",
    "unavailable": "The remote model is temporarily unavailable.",
}


@router.get("/config", summary="Which assistant engine is active")
def config(current_user: User = Depends(get_current_user)) -> dict:
    remote_ready = bool(
        settings.assistant_api_key and settings.assistant_provider != "builtin"
    )
    assistant_status = assistant.remote_status()
    message = _STATUS_MESSAGES[assistant_status]
    retry_after = assistant.cooldown_seconds_remaining()
    retry_at = assistant.cooldown_reset_at()
    if assistant_status == "quota_exhausted":
        label = assistant.cooldown_reset_label()
        if label:
            message = f"{message} Available again around {label}."
    elif assistant_status == "unavailable":
        message = (
            "The remote model is configured but the last request failed; "
            "answers are falling back to the built-in assistant."
        )
    return {
        "provider": settings.assistant_provider if remote_ready else "builtin",
        "model": settings.assistant_model if remote_ready else None,
        "remote_configured": remote_ready,
        "status": assistant_status,
        "message": message,
        "retry_after_seconds": retry_after,
        "retry_at": retry_at,
        # Static: rendering the page must never trigger a paid remote call.
        "suggestions": list(assistant.SUGGESTIONS),
    }


@router.post("", response_model=AssistantResponse, summary="Ask a question")
def ask(
    payload: AssistantRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssistantResponse:
    # The assistant is the only endpoint that can reach a paid external
    # provider, so it is the one that is rate-limited. Keyed by user id so one
    # caller cannot spend another's budget.
    if not assistant_limiter.allow(f"assistant:{current_user.id}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many assistant requests. Please wait a moment and try again.",
        )

    # The context is always the caller's own rows; there is no parameter that
    # could widen it.
    transactions = list(
        db.execute(
            select(Transaction)
            .where(Transaction.user_id == current_user.id)
            .order_by(Transaction.transaction_date.desc())
            .limit(1000)
        ).scalars()
    )

    if payload.include_context:
        budgets = list(
            db.execute(
                select(Budget).where(Budget.user_id == current_user.id)
            ).scalars()
        )
        alerts = list(
            db.execute(
                select(FraudAlert).where(FraudAlert.user_id == current_user.id)
            ).scalars()
        )
    else:
        budgets, alerts = [], []

    result = assistant.respond(
        payload.message,
        transactions,
        budgets,
        alerts,
        history=payload.history,
        include_context=payload.include_context,
    )
    return AssistantResponse(**result)
