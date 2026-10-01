"""Notification and device-token routes.

Push delivery is attempted only when FCM is configured. When it is not, the
in-app notification is still stored and the response says plainly that nothing
was pushed - the app is not told a push succeeded when none was attempted.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.device_token import DevicePlatform, DeviceToken
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.schemas.common import (
    DeviceTokenCreate,
    DeviceTokenResponse,
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
    NotificationWithPushResponse,
    PushResult,
)
from app.services import push

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _find(db: Session, notification_id: int, user_id: int) -> Notification:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


@router.get("", response_model=NotificationListResponse, summary="List notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    notification_type: Optional[NotificationType] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    ).scalar_one()

    rows = list(
        db.execute(
            stmt.order_by(Notification.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(r) for r in rows],
        total=total,
        unread=unread,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count", summary="Unread badge count")
def unread_count(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    ).scalar_one()
    return {"unread": unread, "push_configured": push.fcm_configured()}


@router.post(
    "",
    response_model=NotificationWithPushResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a notification",
)
def create_notification(
    payload: NotificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationWithPushResponse:
    """Store a notification and attempt a push.

    ``push=true`` (default) attempts FCM delivery; ``push=false`` creates the
    in-app row only. When FCM is unconfigured the row is still stored and the
    response reports that no push was attempted.
    """
    notification = Notification(
        user_id=current_user.id,
        notification_type=payload.notification_type,
        title=payload.title,
        body=payload.body,
        data=payload.data,
        deep_link=payload.deep_link,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    result = None
    if payload.push:
        result = push.send_to_user(
            current_user.id,
            notification.title,
            notification.body,
            data=payload.data or {},
            db=db,
        )

    return NotificationWithPushResponse(
        notification=NotificationResponse.model_validate(notification),
        push=PushResult(**result) if result else None,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark one read",
)
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    notification = _find(db, notification_id, current_user.id)
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all", summary="Mark all read")
def mark_all_read(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rows = list(
        db.execute(
            select(Notification).where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
            )
        ).scalars()
    )
    now = datetime.utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.commit()
    return {"updated": len(rows)}


@router.delete(
    "/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete"
)
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    notification = _find(db, notification_id, current_user.id)
    db.delete(notification)
    db.commit()


# ---------------------------------------------------------------------------
# Device tokens
# ---------------------------------------------------------------------------
@router.post(
    "/devices",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device for push",
)
def register_device(
    payload: DeviceTokenCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeviceToken:
    """Register or re-activate a device token.

    The token column is globally unique because FCM treats it as the device
    identity, so a token that already exists is reassigned to the current user
    rather than rejected - this is what happens after a reinstall or an account
    change on the same handset.
    """
    existing = db.execute(
        select(DeviceToken).where(DeviceToken.token == payload.token)
    ).scalar_one_or_none()

    if existing is not None:
        if existing.user_id != current_user.id:
            existing.user_id = current_user.id
        existing.platform = DevicePlatform(payload.platform)
        existing.device_name = payload.device_name
        existing.app_version = payload.app_version
        existing.is_active = True
        existing.last_seen_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    device = DeviceToken(
        user_id=current_user.id,
        token=payload.token,
        platform=DevicePlatform(payload.platform),
        device_name=payload.device_name,
        app_version=payload.app_version,
        is_active=True,
        last_seen_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get(
    "/devices", response_model=List[DeviceTokenResponse], summary="My devices"
)
def list_devices(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> List[DeviceToken]:
    return list(
        db.execute(
            select(DeviceToken)
            .where(DeviceToken.user_id == current_user.id, DeviceToken.is_active.is_(True))
            .order_by(DeviceToken.last_seen_at.desc())
        ).scalars()
    )


@router.delete(
    "/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Unregister"
)
def unregister_device(
    device_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    device = db.get(DeviceToken, device_id)
    if device is None or device.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_active = False
    db.commit()


@router.post("/devices/test", response_model=PushResult, summary="Send a test push")
def test_push(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PushResult:
    if not push.fcm_configured():
        return PushResult(
            success_count=0,
            failure_count=0,
            provider="none",
            message=(
                "FCM is not configured on this server, so no push was sent. "
                "Set FIREBASE_CREDENTIALS_PATH to enable push delivery."
            ),
        )
    result = push.send_to_user(
        current_user.id,
        "Finance-AI test notification",
        "If you can read this on your device, push delivery is working.",
        data={"deep_link": "/settings"},
        db=db,
    )
    return PushResult(
        success_count=result["success_count"],
        failure_count=result["failure_count"],
        provider=result["provider"],
        message=result["message"],
    )
