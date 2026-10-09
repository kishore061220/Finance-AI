"""Production Firebase token verification.

These tests exercise the *real* ``FirebaseTokenVerifier`` and the dependency
chain behind it. The only thing substituted is the single ``firebase_admin``
call that needs live network credentials, so the claim mapping, the error
handling and the request-time authentication path are all covered in CI while
the credential-dependent parts remain exercised where credentials exist.

``test_auth_and_access.py`` proves the dev provider and the authorization
rules; this file proves the Firebase provider maps an identity correctly and
that the same request path rejects bad tokens when Firebase is the active
provider.
"""

from __future__ import annotations

import firebase_admin
import firebase_admin.auth as fb_auth
import pytest

from app.core.security import (
    FirebaseTokenVerifier,
    TokenVerificationError,
    VerifiedIdentity,
)


@pytest.fixture()
def firebase_verifier(monkeypatch):
    """A verifier constructed without touching real credentials.

    ``__init__`` only initialises an app when none exists, so a placeholder in
    ``firebase_admin._apps`` keeps construction side-effect free.
    """
    monkeypatch.setitem(firebase_admin._apps, "[DEFAULT]", object())
    return FirebaseTokenVerifier()


class TestFirebaseClaimMapping:
    def test_maps_verified_claims(self, firebase_verifier, monkeypatch):
        monkeypatch.setattr(
            fb_auth,
            "verify_id_token",
            lambda token, **kwargs: {
                "uid": "firebase-uid-123",
                "email": "user@example.com",
                "email_verified": True,
                "name": "Real User",
            },
        )
        identity = firebase_verifier.verify("good-token")
        assert identity == VerifiedIdentity(
            subject="firebase-uid-123",
            email="user@example.com",
            email_verified=True,
            display_name="Real User",
            provider="firebase",
        )

    def test_falls_back_to_sub_when_uid_absent(self, firebase_verifier, monkeypatch):
        monkeypatch.setattr(
            fb_auth,
            "verify_id_token",
            lambda token, **kwargs: {"sub": "sub-only", "email": "s@example.com"},
        )
        identity = firebase_verifier.verify("good-token")
        assert identity.subject == "sub-only"
        assert identity.email_verified is False
        assert identity.display_name is None

    def test_unverified_email_is_reported(self, firebase_verifier, monkeypatch):
        monkeypatch.setattr(
            fb_auth,
            "verify_id_token",
            lambda token, **kwargs: {
                "uid": "u",
                "email": "e@example.com",
                "email_verified": False,
            },
        )
        assert firebase_verifier.verify("t").email_verified is False

    def test_firebase_rejection_becomes_token_error(self, firebase_verifier, monkeypatch):
        def boom(token, **kwargs):
            raise ValueError("Token expired")

        monkeypatch.setattr(fb_auth, "verify_id_token", boom)
        with pytest.raises(TokenVerificationError):
            firebase_verifier.verify("bad-token")


class _StubFirebaseVerifier:
    """Stands in for FirebaseTokenVerifier at the deps boundary."""

    provider_name = "firebase"

    def verify(self, token: str) -> VerifiedIdentity:
        if token == "valid-firebase-token":
            return VerifiedIdentity(
                subject="fb-uid-1",
                email="firebase@example.com",
                email_verified=True,
                display_name="Firebase User",
                provider="firebase",
            )
        raise TokenVerificationError("rejected")


@pytest.fixture()
def firebase_provider(monkeypatch):
    """Swap the verifier the dependency layer resolves, nothing else.

    Ownership, provisioning and the 401 path all still run through the real
    dependency chain; only cryptographic verification is substituted.
    """
    import app.core.deps as deps

    monkeypatch.setattr(deps, "get_token_verifier", lambda: _StubFirebaseVerifier())


class TestFirebaseThroughTheDependency:
    def test_valid_token_authenticates_and_provisions(self, client, db, firebase_provider):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer valid-firebase-token"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "firebase@example.com"

        from app.models.user import User

        user = db.query(User).filter(User.firebase_uid == "fb-uid-1").one()
        assert user.email == "firebase@example.com"

    def test_invalid_token_is_401(self, client, firebase_provider):
        response = client.get(
            "/api/auth/me", headers={"Authorization": "Bearer forged"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired authentication token."

    def test_missing_token_is_401(self, client, firebase_provider):
        assert client.get("/api/auth/me").status_code == 401
