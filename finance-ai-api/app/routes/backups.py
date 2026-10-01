"""Backup routes.

The backup record is the audit trail. When no cloud provider is configured the
endpoint still runs and still writes a record - it reports the truth instead of
raising a 500 or pretending a backup succeeded.

Restore is split into a read-only preview and an explicitly confirmed apply, so
that a user can see exactly what will change before anything is written.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.backup import BackupRecord
from app.models.user import User
from app.schemas.common import (
    BackupListResponse,
    BackupRequest,
    BackupStatusResponse,
    RestoreRequest,
    RestoreResponse,
)
from app.services import backup as backup_service
from app.services import restore as restore_service

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("/providers", summary="Which backup providers are usable")
def providers(current_user: User = Depends(get_current_user)) -> dict:
    configured = backup_service.available_providers()
    return {
        "providers": configured,
        "default_provider": backup_service.default_provider(),
        "cloud_configured": any(configured.values()),
        "message": (
            "At least one cloud provider is configured."
            if any(configured.values())
            else (
                "No cloud backup provider is configured. Backups will be written "
                "to the server's local directory. Set FIREBASE_CREDENTIALS_PATH, "
                "GCS_BUCKET + GOOGLE_APPLICATION_CREDENTIALS, or "
                "GOOGLE_DRIVE_CREDENTIALS_PATH to enable cloud backup."
            )
        ),
    }


@router.post(
    "",
    response_model=BackupStatusResponse,
    summary="Create a backup now",
)
def create_backup(
    payload: BackupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BackupRecord:
    record = backup_service.run_backup(
        db,
        current_user.id,
        provider=payload.provider,
        include_fraud_alerts=payload.include_fraud_alerts,
        include_budgets=payload.include_budgets,
        include_loans=payload.include_loans,
    )
    if record.status.value == "FAILED":
        # A failed backup is a real outcome, so it is reported as a 502 with the
        # record attached rather than being hidden behind a 200.
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Backup failed.",
                "provider": record.provider.value,
                "reason": record.error_message,
                "backup_id": record.id,
            },
        )
    return record


@router.get("", response_model=BackupListResponse, summary="Backup history")
def list_backups(
    provider: str = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BackupListResponse:
    stmt = select(BackupRecord).where(BackupRecord.user_id == current_user.id)
    if provider:
        stmt = stmt.where(BackupRecord.provider == provider)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows: List[BackupRecord] = list(
        db.execute(
            stmt.order_by(BackupRecord.created_at.desc()).limit(limit).offset(offset)
        ).scalars()
    )
    cloud_configured = any(backup_service.available_providers().values())
    return BackupListResponse(
        items=[BackupStatusResponse.model_validate(r) for r in rows],
        total=total,
        provider=provider,
        configured=cloud_configured,
        message=(
            "Cloud backup provider configured."
            if cloud_configured
            else "No cloud provider configured; recent backups used the local provider."
        ),
    )


@router.get("/{backup_id}", response_model=BackupStatusResponse, summary="Get one")
def get_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BackupRecord:
    record = db.get(BackupRecord, backup_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Backup record not found")
    return record


@router.post(
    "/{backup_id}/verify",
    summary="Re-verify a stored backup's checksum",
)
def verify_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Re-hash a local backup file and compare it with the stored checksum.

    Cloud backups are not downloadable with the credentials this app holds, so
    only LOCAL backups can be verified here; others report that plainly.
    """
    record = db.get(BackupRecord, backup_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Backup record not found")

    if record.provider.value != "LOCAL":
        return {
            "verified": False,
            "provider": record.provider.value,
            "message": (
                f"{record.provider.value} backups are verified server-side at "
                "upload time; this server cannot download them to re-hash."
            ),
        }
    if not record.remote_path:
        return {"verified": False, "message": "This record has no stored file path."}

    from pathlib import Path

    path = Path(record.remote_path)
    if not path.exists():
        return {
            "verified": False,
            "message": f"Backup file is missing at {path}.",
        }

    actual = backup_service.checksum(path.read_bytes())
    return {
        "verified": actual == record.checksum,
        "provider": "LOCAL",
        "expected_checksum": record.checksum,
        "actual_checksum": actual,
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def _owned_backup(db: Session, backup_id: int, current_user: User) -> BackupRecord:
    """Fetch a backup the caller owns, or 404.

    A backup belonging to somebody else must be indistinguishable from one that
    does not exist, or the endpoint becomes a probe for valid backup ids.
    """
    record = db.get(BackupRecord, backup_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Backup record not found")
    return record


def _restore_error(exc: restore_service.RestoreError) -> HTTPException:
    """Map a refusal onto a status code that matches why it was refused."""
    status_by_code = {
        "backup_not_found": 404,
        "backup_not_restorable": 409,
        "backup_file_missing": 410,
        "checksum_mismatch": 409,
        "payload_owner_missing": 409,
        "payload_owner_invalid": 409,
        "provider_not_configured": 503,
        "provider_unsupported": 501,
        "unsupported_version": 409,
        "download_failed": 502,
        "payload_not_json": 409,
        "payload_not_object": 409,
        "backup_no_path": 409,
        "backup_no_checksum": 409,
    }
    return HTTPException(
        status_code=status_by_code.get(exc.code, 400),
        detail={"error": exc.message, "code": exc.code},
    )


@router.get(
    "/{backup_id}/restore/preview",
    response_model=RestoreResponse,
    summary="Preview what a restore would change (read-only)",
)
def preview_restore(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RestoreResponse:
    """Download, checksum-verify, and report the plan. Writes nothing.

    This is safe to call repeatedly and is the intended way for a client to
    show a user what ``POST /restore`` is about to do.
    """
    record = _owned_backup(db, backup_id, current_user)
    try:
        plan = restore_service.plan_restore(db, record, current_user.id)
    except restore_service.RestoreError as exc:
        raise _restore_error(exc) from exc
    return RestoreResponse(**plan.as_dict())


@router.post(
    "/{backup_id}/restore",
    response_model=RestoreResponse,
    summary="Restore a backup (upsert; requires confirm=true)",
)
def restore_backup(
    backup_id: int,
    payload: RestoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RestoreResponse:
    """Upsert the backup into the caller's account.

    Upserts on natural keys, so restoring the same backup twice inserts nothing
    the second time. Rows whose natural key collides but whose contents differ
    are reported as conflicts and left untouched.
    """
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "error": (
                    "Restoring requires confirm=true. Call "
                    "/restore/preview first to see what will change."
                ),
                "code": "confirmation_required",
            },
        )

    record = _owned_backup(db, backup_id, current_user)
    try:
        result = restore_service.apply_restore(db, record, current_user.id)
    except restore_service.RestoreError as exc:
        raise _restore_error(exc) from exc
    return RestoreResponse(**result.as_dict())
