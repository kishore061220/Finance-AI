"""Push notification delivery via Firebase Cloud Messaging.

The sender is resolved lazily so the API still boots (and every non-push
feature keeps working) when FCM credentials are absent. ``send_to_user``
returns a structured result describing exactly what happened - it never
reports success for a message it did not deliver.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_sender = None
_sender_state: Optional[bool] = None  # None = not attempted, False = unavailable


def fcm_configured() -> bool:
    """True when the environment has what FCM needs.

    FCM uses the same service account as Firebase Authentication, so a valid
    Firebase configuration implies FCM is available.
    """
    return bool(settings.firebase_enabled)


def _get_sender():
    global _sender, _sender_state
    if _sender_state is not None:
        return _sender
    try:
        from firebase_admin import messaging

        # Reuses the app initialised by FirebaseTokenVerifier.
        _sender = messaging.send
        _sender_state = True
    except Exception as exc:  # pragma: no cover - missing SDK/creds
        logger.warning("FCM unavailable: %s", exc)
        _sender = None
        _sender_state = False
    return _sender


def reset_sender() -> None:
    """Test hook."""
    global _sender, _sender_state
    _sender = None
    _sender_state = None


def send_to_tokens(
    tokens: Iterable[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
) -> Dict:
    """Send one message to many device tokens.

    ``data`` values must be strings (FCM constraint), so they are coerced.
    """
    token_list: List[str] = [t for t in tokens if t]
    if not token_list:
        return {
            "success_count": 0,
            "failure_count": 0,
            "provider": "fcm",
            "message": "No active device tokens are registered for this user.",
        }

    sender = _get_sender()
    if sender is None:
        return {
            "success_count": 0,
            "failure_count": len(token_list),
            "provider": "fcm",
            "message": (
                "FCM is not configured on the server. Configure Firebase "
                "credentials to enable push delivery; the in-app notification "
                "was still created."
            ),
        }

    from firebase_admin import messaging

    success = 0
    failures: List[str] = []
    for token in token_list:
        try:
            sender(
                messaging.Message(
                    token=token,
                    notification=messaging.Notification(title=title, body=body),
                    data={k: str(v) for k, v in (data or {}).items()},
                )
            )
            success += 1
        except Exception as exc:
            logger.warning("FCM send failed: %s", exc)
            failures.append(str(exc))

    message = "Delivered." if not failures else f"{len(failures)} delivery failure(s)."
    return {
        "success_count": success,
        "failure_count": len(failures),
        "provider": "fcm",
        "message": message,
    }


def send_to_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict] = None,
    db=None,
) -> Dict:
    """Send to every active token registered by a user.

    Returns a result dict; the caller is responsible for the in-app
    Notification row, which is stored regardless of push delivery.

    Pass ``db`` to reuse the request's session. When omitted a short-lived
    session is opened, so the helper is still usable from background jobs.
    """
    from sqlalchemy import select

    from app.models.device_token import DeviceToken

    def _tokens(session):
        return list(
            session.execute(
                select(DeviceToken.token).where(
                    DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True)
                )
            ).scalars()
        )

    if db is not None:
        tokens = _tokens(db)
    else:
        from app.database.connection import SessionLocal

        owned = SessionLocal()
        try:
            tokens = _tokens(owned)
        finally:
            owned.close()

    return send_to_tokens(tokens, title, body, data)
