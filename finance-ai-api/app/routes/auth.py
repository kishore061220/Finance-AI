"""Authentication routes.

Firebase is the production authentication system. The client obtains an ID
token from the Firebase SDK and sends it as ``Authorization: Bearer <token>``.

There is no password login and no client-supplied user id: the user is always
resolved from the verified token. The development token endpoint exists only
when ``ALLOW_DEV_AUTH=true`` **and** Firebase is not configured; it returns 404
as soon as Firebase is enabled, so it can never become a second live
authentication path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import issue_dev_token
from app.database.connection import get_db
from app.models.budget import Budget
from app.models.family import FamilyMember, MemberStatus
from app.models.loan import Loan
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.user import (
    DevTokenRequest,
    DevTokenResponse,
    RefreshResponse,
    UserProfileResponse,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _disabled_dev_auth() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            "Development token issuance is disabled. Configure Firebase "
            "Authentication for real deployments."
        ),
    )


@router.get("/config", summary="Which auth provider this server is using")
def auth_config() -> dict:
    """Lets the client decide whether to show a Firebase sign-in flow."""
    return {
        "provider": "firebase" if settings.firebase_enabled else (
            "dev" if settings.dev_auth_active else "unconfigured"
        ),
        "firebase_enabled": settings.firebase_enabled,
        "registration_enabled": settings.firebase_enabled,
        "app_env": settings.app_env,
    }


@router.post(
    "/dev-token",
    response_model=DevTokenResponse,
    summary="Mint a development token (local only)",
)
def dev_token(payload: DevTokenRequest) -> DevTokenResponse:
    if settings.firebase_enabled or not settings.dev_auth_active:
        raise _disabled_dev_auth()
    minutes = payload.expires_minutes or settings.access_token_expire_minutes
    token = issue_dev_token(
        subject=payload.subject,
        email=payload.email,
        display_name=payload.name,
        expires_minutes=minutes,
    )
    return DevTokenResponse(access_token=token, expires_in=minutes * 60)


@router.post("/refresh", response_model=RefreshResponse, summary="Token refresh")
def refresh() -> RefreshResponse:
    """Firebase ID tokens are refreshed by the client SDK, not the server."""
    return RefreshResponse()


@router.get("/me", response_model=UserResponse, summary="Current user")
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/profile", response_model=UserProfileResponse, summary="Profile with counts")
def profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserProfileResponse:
    def count(model, column=None):
        stmt = select(func.count()).select_from(model)
        if column is not None:
            stmt = stmt.where(column == current_user.id)
        return db.execute(stmt).scalar_one()

    family_count = db.execute(
        select(func.count())
        .select_from(FamilyMember)
        .where(
            FamilyMember.user_id == current_user.id,
            FamilyMember.status == MemberStatus.ACTIVE,
        )
    ).scalar_one()

    return UserProfileResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        email_verified=current_user.email_verified,
        phone_number=current_user.phone_number,
        created_at=current_user.created_at,
        transaction_count=count(Transaction, Transaction.user_id),
        budget_count=count(Budget, Budget.user_id),
        family_count=family_count,
        loan_count=count(Loan, Loan.user_id),
    )


@router.patch("/profile", response_model=UserResponse, summary="Update profile")
def update_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post(
    "/logout", summary="Client-side sign out acknowledgement", status_code=200
)
def logout(current_user: User = Depends(get_current_user)) -> dict:
    """Tokens are stateless; the client discards them.

    The server records the sign-out time so the audit trail is complete.
    """
    from datetime import datetime

    logger.info("User %s signed out", current_user.id)
    return {"signed_out": True, "server_time": datetime.utcnow().isoformat() + "Z"}
