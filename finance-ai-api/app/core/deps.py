"""Shared FastAPI dependencies.

The critical guarantee provided here: the authenticated identity is derived
*only* from a cryptographically verified token. Route handlers never accept a
``user_id`` from the client for authorization purposes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    TokenVerificationError,
    VerifiedIdentity,
    get_token_verifier,
)
from app.database.connection import get_db
from app.models.user import User

# auto_error=False lets us return a consistent JSON error shape.
bearer_scheme = HTTPBearer(auto_error=False, description="Firebase ID token")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. A valid Firebase ID token is required.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_verified_identity(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> VerifiedIdentity:
    """Verify the bearer token and return the identity it asserts."""
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION
    try:
        return get_token_verifier().verify(credentials.credentials)
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    identity: VerifiedIdentity = Depends(get_verified_identity),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the verified identity to a local ``users`` row.

    The row is provisioned on first authenticated request. This is the only
    place where a ``user_id`` is established, and it comes from the token.
    """
    user = db.execute(
        select(User).where(User.firebase_uid == identity.subject)
    ).scalar_one_or_none()

    if user is None and identity.email:
        # Link a pre-existing legacy account on first Firebase sign-in.
        user = db.execute(
            select(User).where(User.email == identity.email)
        ).scalar_one_or_none()
        if user is not None:
            user.firebase_uid = identity.subject
            user.email_verified = user.email_verified or identity.email_verified
            if identity.display_name and not user.name:
                user.name = identity.display_name
            user.last_login_at = _utcnow()
            db.commit()
            db.refresh(user)

    if user is None:
        if not identity.email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The authenticated account has no email address, which is "
                    "required to provision a Finance-AI profile."
                ),
            )
        user = User(
            firebase_uid=identity.subject,
            email=identity.email,
            name=identity.display_name or identity.email.split("@")[0],
            password_hash=None,
            email_verified=identity.email_verified,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated."
        )

    user.last_login_at = _utcnow()
    db.commit()
    db.refresh(user)
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")
    return current_user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    """Guard for administrative operations such as model training.

    ``OWNER`` is the elevated role in this schema. It is checked here rather
    than in each handler so the rule exists in exactly one place.
    """
    if current_user.role.value != "OWNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires the OWNER role.",
        )
    return current_user


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = [
    "bearer_scheme",
    "get_current_active_user",
    "get_current_user",
    "get_db",
    "get_verified_identity",
    "require_owner",
    "settings",
]