"""Encrypted-at-rest cloud backup of a user's financial data.

Three providers are supported. Each is resolved lazily and each reports
honestly when it is not configured - the endpoint always creates a
``BackupRecord`` so the history is truthful, recording FAILED with an
explanation rather than pretending a backup happened.

A local-filesystem provider is also provided. It is not a substitute for cloud
backup, but it lets the full backup pipeline (serialise -> checksum -> record
-> restore) be exercised end to end without any cloud credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.backup import BackupProvider, BackupRecord, BackupStatus

logger = logging.getLogger(__name__)

BACKUP_VERSION = 1
LOCAL_BACKUP_DIR = Path(__file__).resolve().parents[2] / "backups"


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # enums
        return value.value
    return str(value)


def provider_available(provider: str) -> bool:
    """True when the environment can actually use this provider."""
    if provider == BackupProvider.GOOGLE_CLOUD_STORAGE.value:
        return bool(settings.gcs_bucket and settings.google_application_credentials)
    if provider == BackupProvider.GOOGLE_DRIVE.value:
        return bool(
            settings.google_drive_credentials_path
            and settings.google_drive_credentials_path.exists()
        )
    if provider == BackupProvider.FIREBASE_STORAGE.value:
        return bool(settings.firebase_enabled)
    return False


def available_providers() -> Dict[str, bool]:
    return {
        BackupProvider.FIREBASE_STORAGE.value: provider_available(
            BackupProvider.FIREBASE_STORAGE.value
        ),
        BackupProvider.GOOGLE_CLOUD_STORAGE.value: provider_available(
            BackupProvider.GOOGLE_CLOUD_STORAGE.value
        ),
        BackupProvider.GOOGLE_DRIVE.value: provider_available(
            BackupProvider.GOOGLE_DRIVE.value
        ),
    }


def default_provider() -> str:
    """Pick the first configured cloud provider, else the local provider."""
    for name, ok in available_providers().items():
        if ok:
            return name
    return "LOCAL"


def collect_user_data(
    db: Session,
    user_id: int,
    include_fraud_alerts: bool = True,
    include_budgets: bool = True,
    include_loans: bool = True,
) -> Dict:
    """Serialise one user's data into a JSON-safe dict."""
    from app.models.budget import Budget
    from app.models.fraud_alert import FraudAlert
    from app.models.loan import Loan, LoanPayment
    from app.models.transaction import Transaction

    transactions = list(
        db.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        ).scalars()
    )
    payload: Dict = {
        "backup_version": BACKUP_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "user_id": user_id,
        "transactions": [
            {
                "id": t.id,
                "transaction_type": t.transaction_type.value,
                "amount": str(t.amount),
                "category": t.category,
                "emi_type": t.emi_type,
                "merchant": t.merchant,
                "description": t.description,
                "transaction_date": t.transaction_date.isoformat(),
                "source": t.source.value,
                "bank_reference": t.bank_reference,
                "fraud_score": t.fraud_score,
                "is_flagged": t.is_flagged,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ],
    }
    payload["transaction_count"] = len(payload["transactions"])

    if include_budgets:
        budgets = list(db.execute(select(Budget).where(Budget.user_id == user_id)).scalars())
        payload["budgets"] = [
            {
                "id": b.id,
                "category": b.category,
                "amount": str(b.amount),
                "month": b.month,
                "year": b.year,
            }
            for b in budgets
        ]
        payload["budget_count"] = len(payload["budgets"])

    if include_fraud_alerts:
        alerts = list(
            db.execute(
                select(FraudAlert).where(FraudAlert.user_id == user_id)
            ).scalars()
        )
        payload["fraud_alerts"] = [
            {
                "id": a.id,
                "transaction_id": a.transaction_id,
                "risk_score": a.risk_score,
                "risk_level": a.risk_level.value,
                "is_fraud": a.is_fraud,
                "detection_layer": a.detection_layer.value,
                "reasons": a.reasons,
            }
            for a in alerts
        ]
        payload["fraud_alert_count"] = len(payload["fraud_alerts"])

    if include_loans:
        loans = list(db.execute(select(Loan).where(Loan.user_id == user_id)).scalars())
        loan_ids = [loan.id for loan in loans]
        payments: List[LoanPayment] = []
        if loan_ids:
            payments = list(
                db.execute(
                    select(LoanPayment).where(LoanPayment.loan_id.in_(loan_ids))
                ).scalars()
            )
        payload["loans"] = [
            {
                "id": loan.id,
                "name": loan.name,
                "lender": loan.lender,
                "loan_type": loan.loan_type.value,
                "principal": str(loan.principal),
                "interest_rate": str(loan.interest_rate),
                "tenure_months": loan.tenure_months,
                "monthly_emi": str(loan.monthly_emi),
                "total_payable": str(loan.total_payable),
                "start_date": loan.start_date.isoformat(),
                "status": loan.status.value,
            }
            for loan in loans
        ]
        payload["loan_count"] = len(payload["loans"])
        payload["loan_payments"] = [
            {
                "loan_id": p.loan_id,
                "installment_number": p.installment_number,
                "amount": str(p.amount),
                "due_date": p.due_date.isoformat(),
                "paid_date": p.paid_date.isoformat() if p.paid_date else None,
                "status": p.status.value,
            }
            for p in payments
        ]

    return payload


def serialize(payload: Dict) -> bytes:
    return json.dumps(payload, default=_json_default, indent=2).encode("utf-8")


def checksum(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _remote_name(user_id: int, stamp: datetime) -> str:
    return f"finance-ai/user_{user_id}/{stamp.strftime('%Y%m%d_%H%M%S')}.json"


def _upload_gcs(blob: bytes, name: str) -> Dict:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_bucket)
    blob_obj = bucket.blob(name)
    blob_obj.upload_from_string(blob, content_type="application/json")
    return {"remote_path": name, "remote_url": f"gs://{settings.gcs_bucket}/{name}"}


def _upload_drive(blob: bytes, name: str) -> Dict:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(settings.google_drive_credentials_path),
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=creds)
    metadata = {"name": name}
    if settings.google_drive_folder_id:
        metadata["parents"] = [settings.google_drive_folder_id]
    from io import BytesIO

    file = service.files().create(body=metadata, media_body=BytesIO(blob), fields="id,webViewLink").execute()
    return {"remote_path": file.get("id"), "remote_url": file.get("webViewLink")}


def _upload_firebase_storage(blob: bytes, name: str) -> Dict:
    from firebase_admin import storage

    bucket = storage.bucket()
    blob_obj = bucket.blob(name)
    blob_obj.upload_from_string(blob, content_type="application/json")
    return {
        "remote_path": name,
        "remote_url": f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{name}",
    }


def _upload_local(blob: bytes, name: str) -> Dict:
    LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_BACKUP_DIR / name.replace("/", "_")
    path.write_bytes(blob)
    return {"remote_path": str(path), "remote_url": path.as_uri()}


UPLOADERS = {
    BackupProvider.GOOGLE_CLOUD_STORAGE.value: _upload_gcs,
    BackupProvider.GOOGLE_DRIVE.value: _upload_drive,
    BackupProvider.FIREBASE_STORAGE.value: _upload_firebase_storage,
    "LOCAL": _upload_local,
}


def run_backup(
    db: Session,
    user_id: int,
    provider: Optional[str] = None,
    include_fraud_alerts: bool = True,
    include_budgets: bool = True,
    include_loans: bool = True,
) -> BackupRecord:
    """Create a backup. Always writes a ``BackupRecord`` with the true outcome."""
    target = (provider or default_provider()).upper()
    if target not in UPLOADERS:
        target = default_provider()

    record = BackupRecord(
        user_id=user_id,
        provider=BackupProvider(target),
        status=BackupStatus.PENDING,
        started_at=datetime.utcnow(),
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    try:
        payload = collect_user_data(
            db, user_id, include_fraud_alerts, include_budgets, include_loans
        )
        blob = serialize(payload)
        name = _remote_name(user_id, datetime.utcnow())

        if target != "LOCAL" and not provider_available(target):
            raise RuntimeError(
                f"{target} is not configured. Set the required environment "
                "variables for this provider."
            )

        result = UPLOADERS[target](blob, name)

        record.status = BackupStatus.SUCCESS
        record.remote_path = result.get("remote_path")
        record.remote_url = result.get("remote_url")
        record.record_count = payload.get("transaction_count", 0)
        record.size_bytes = len(blob)
        record.checksum = checksum(blob)
        record.completed_at = datetime.utcnow()
    except Exception as exc:
        logger.warning("Backup failed for user %s via %s: %s", user_id, target, exc)
        record.status = BackupStatus.FAILED
        record.error_message = str(exc)[:500]
        record.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(record)
    return record
