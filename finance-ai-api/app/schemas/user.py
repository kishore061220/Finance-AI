"""Authentication and user schemas.

Firebase ID tokens are obtained by the client from Firebase Authentication. The
backend never accepts a client-supplied ``user_id``; it derives the user from
the verified token. The legacy password login schemas are retained only for
pre-migration compatibility and are disabled once Firebase is active.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class DevTokenRequest(BaseModel):
    """Development-only token minting.

    Rejected with 404 whenever Firebase is configured, so this endpoint can
    never become a live authentication path in production.
    """

    subject: str = Field(..., min_length=1, max_length=128, description="Firebase UID")
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(default=None, max_length=100)
    expires_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    provider: str = "dev"


class RefreshResponse(BaseModel):
    """Firebase SDKs refresh ID tokens client-side; the API acknowledges."""

    refreshed: bool = True
    note: str = (
        "Firebase ID tokens are refreshed by the client SDK. Call "
        "getIdToken(true) and retry with the new Authorization header."
    )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class UserResponse(ORMModel):
    id: int
    name: str
    email: Optional[EmailStr] = None
    role: UserRole
    is_active: bool
    email_verified: bool
    phone_number: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone_number: Optional[str] = Field(default=None, max_length=32)


class UserProfileResponse(ORMModel):
    id: int
    name: str
    email: Optional[EmailStr] = None
    role: UserRole
    email_verified: bool
    phone_number: Optional[str] = None
    created_at: Optional[datetime] = None
    transaction_count: int = 0
    budget_count: int = 0
    family_count: int = 0
    loan_count: int = 0


class FamilyMemberSummary(ORMModel):
    id: int
    name: str
    email: Optional[EmailStr] = None
    role: UserRole


__all__ = [
    "DevTokenRequest",
    "DevTokenResponse",
    "FamilyMemberSummary",
    "ORMModel",
    "RefreshResponse",
    "UserProfileResponse",
    "UserResponse",
    "UserRole",
    "UserUpdate",
]
