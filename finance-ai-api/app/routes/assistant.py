"""Assistant routes.

The assistant answers from the caller's own data. The response always declares
which engine replied and, when the configured LLM provider is unavailable, that
it fell back to the built-in engine.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
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

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/config", summary="Which assistant engine is active")
def config(current_user: User = Depends(get_current_user)) -> dict:
    remote_ready = bool(settings.assistant_api_key)
    return {
        "provider": settings.assistant_provider if remote_ready else "builtin",
        "model": settings.assistant_model if remote_ready else None,
        "remote_configured": remote_ready,
        "message": (
            f"Using {settings.assistant_provider} for answers."
            if remote_ready
            else (
                "Using the built-in rule assistant. Set ASSISTANT_API_KEY to "
                "enable the remote model."
            )
        ),
        "suggestions": assistant.respond(
            "what can you do", [], [], [], include_context=False
        )["suggestions"],
    }


@router.post("", response_model=AssistantResponse, summary="Ask a question")
def ask(
    payload: AssistantRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssistantResponse:
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
