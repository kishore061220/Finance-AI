"""Authentication and cryptographic helpers.

Authentication architecture (single, authoritative path)
--------------------------------------------------------
1. A client obtains an identity token from **Firebase Authentication**.
2. The client sends it as ``Authorization: Bearer <token>``.
3. The backend verifies the token with ``firebase_admin``.

Two mutually exclusive token providers exist and only one can ever be active:

* ``FirebaseTokenVerifier``  - the production provider. Active whenever
  Firebase credentials are configured. This is the FINAL architecture.
* ``DevTokenVerifier``       - a local-development provider used only when
  ``ALLOW_DEV_AUTH=true`` **and** no Firebase credentials exist. It is
  automatically inert once Firebase is configured, so there is never a
  window in production where a second authentication system is live.

The authenticated identity is *always* derived from a verified token.
``user_id`` supplied by a client is never trusted for authorization.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# ---------------------------------------------------------------------------
# Password hashing (used by the dev provider and by legacy migration)
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:  # pragma: no cover - malformed hash
        return False


# ---------------------------------------------------------------------------
# Token providers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VerifiedIdentity:
    """A cryptographically verified identity returned by a token provider."""

    subject: str
    email: Optional[str]
    email_verified: bool
    display_name: Optional[str]
    provider: str


class TokenVerificationError(Exception):
    """Raised when a bearer token cannot be verified."""


class TokenVerifier(ABC):
    @abstractmethod
    def verify(self, token: str) -> VerifiedIdentity:
        """Verify a bearer token or raise :class:`TokenVerificationError`."""


class FirebaseTokenVerifier(TokenVerifier):
    """Verifies Firebase ID tokens. This is the production provider."""

    provider_name = "firebase"

    def __init__(self) -> None:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:  # pragma: no cover - process singleton
            if settings.firebase_credentials_json:
                options = json.loads(settings.firebase_credentials_json)
                cred = credentials.Certificate(options)
            elif settings.firebase_credentials_path and settings.firebase_credentials_path.exists():
                cred = credentials.Certificate(str(settings.firebase_credentials_path))
            else:  # pragma: no cover - ADC
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})

    def verify(self, token: str) -> VerifiedIdentity:
        from firebase_admin import auth as fb_auth

        try:
            decoded = fb_auth.verify_id_token(token, app=None, check_revoked=False)
        except Exception as exc:
            raise TokenVerificationError(f"Firebase token rejected: {exc}") from exc

        return VerifiedIdentity(
            subject=str(decoded.get("uid") or decoded.get("sub") or ""),
            email=decoded.get("email"),
            email_verified=bool(decoded.get("email_verified", False)),
            display_name=decoded.get("name"),
            provider=self.provider_name,
        )


class DevTokenVerifier(TokenVerifier):
    """Local-development token provider.

    Signs/verifies short-lived HS256 tokens using ``SECRET_KEY``. Only used
    when Firebase is not configured and ``ALLOW_DEV_AUTH`` is enabled.
    """

    provider_name = "dev"

    def verify(self, token: str) -> VerifiedIdentity:
        if not settings.secret_key:
            raise TokenVerificationError("SECRET_KEY is not configured")
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"require": ["exp", "sub", "aud"]},
                audience=settings.app_name,
            )
        except JWTError as exc:
            raise TokenVerificationError(f"Dev token rejected: {exc}") from exc

        return VerifiedIdentity(
            subject=str(payload["sub"]),
            email=payload.get("email"),
            email_verified=bool(payload.get("email_verified", False)),
            display_name=payload.get("name"),
            provider=self.provider_name,
        )


def issue_dev_token(
    subject: str,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    email_verified: bool = True,
    expires_minutes: Optional[int] = None,
) -> str:
    """Mint a development token (dev provider only)."""
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY must be set to issue development tokens")
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(subject),
        "aud": settings.app_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "iss": settings.app_name,
        "email_verified": email_verified,
    }
    if email:
        claims["email"] = email
    if display_name:
        claims["name"] = display_name
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


_verifier: Optional[TokenVerifier] = None
_verifier_initialised = False


def get_token_verifier() -> TokenVerifier:
    """Return the single active token provider for this process."""
    global _verifier, _verifier_initialised
    if _verifier_initialised:
        assert _verifier is not None
        return _verifier

    if settings.firebase_enabled:
        _verifier = FirebaseTokenVerifier()
        logger.info("Authentication provider: Firebase Authentication")
    elif settings.dev_auth_active:
        _verifier = DevTokenVerifier()
        logger.warning(
            "Authentication provider: DEV token provider. "
            "Configure Firebase to enable production authentication."
        )
    else:  # pragma: no cover - misconfiguration
        raise RuntimeError(
            "No authentication provider is configured. Set Firebase credentials "
            "(FIREBASE_PROJECT_ID + FIREBASE_CREDENTIALS_PATH) or explicitly set "
            "ALLOW_DEV_AUTH=true together with SECRET_KEY for local development."
        )

    _verifier_initialised = True
    return _verifier


def reset_token_verifier() -> None:
    """Test hook - forces the verifier to be rebuilt on next use."""
    global _verifier, _verifier_initialised
    _verifier = None
    _verifier_initialised = False