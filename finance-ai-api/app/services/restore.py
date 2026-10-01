"""Restore a user's own backup back into the database.

Restore is the most destructive operation this API offers, so it is built to be
boring and reversible rather than clever:

1. **Verify first.** The stored blob is re-hashed and compared against the
   checksum recorded at upload time. A mismatch aborts before any write.
2. **Preview, then confirm.** :func:`plan_restore` performs every read and every
   decision but commits nothing, so the caller can show exact per-table
   insert/update/skip counts before :func:`apply_restore` is allowed to run.
3. **Never trust the payload for identity.** Primary keys inside the backup are
   treated as *hints* used only to stitch child rows back to their parents.
   Every written row is stamped with the authenticated ``user_id``, and a
   payload whose own ``user_id`` belongs to somebody else is refused outright.
4. **Upsert on natural keys**, not primary keys, so restoring the same backup
   twice is a no-op rather than a duplicate.
5. **Refuse to guess.** When a row's natural key collides but its contents
   differ, it is reported as a conflict and left alone. Silently overwriting
   somebody's newer data is not a restore.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.backup import BackupProvider, BackupRecord
from app.services import backup as backup_service

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = frozenset({backup_service.BACKUP_VERSION})


class RestoreError(Exception):
    """A restore could not be attempted safely. Nothing was written."""

    def __init__(self, message: str, *, code: str = "restore_error"):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _download_gcs(remote_path: str) -> bytes:
    from google.cloud import storage

    client = storage.Client()
    return client.bucket(settings.gcs_bucket).blob(remote_path).download_as_bytes()


def _download_drive(remote_path: str) -> bytes:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(settings.google_drive_credentials_path),
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=creds)
    return service.files().get_media(fileId=remote_path).execute()


def _download_firebase_storage(remote_path: str) -> bytes:
    from firebase_admin import storage

    return storage.bucket().blob(remote_path).download_as_bytes()


def _download_local(remote_path: str) -> bytes:
    from pathlib import Path

    path = Path(remote_path)
    if not path.exists():
        raise RestoreError(
            f"The backup file is no longer on the server at {path}. It may have "
            "been rotated out. Restore from a cloud copy instead.",
            code="backup_file_missing",
        )
    return path.read_bytes()


DOWNLOADERS = {
    BackupProvider.GOOGLE_CLOUD_STORAGE.value: _download_gcs,
    BackupProvider.GOOGLE_DRIVE.value: _download_drive,
    BackupProvider.FIREBASE_STORAGE.value: _download_firebase_storage,
    "LOCAL": _download_local,
}


def fetch_and_verify(record: BackupRecord) -> Tuple[Dict, str]:
    """Download the blob, verify its checksum, and return ``(payload, checksum)``.

    Raises :class:`RestoreError` if the checksum is missing, mismatched, or the
    backup is not in a restorable state. The checksum is verified on *every*
    attempt, including during preview, because a preview of a corrupted file is
    worse than no preview at all.
    """
    if record.status.value != "SUCCESS":
        raise RestoreError(
            f"Backup #{record.id} is {record.status.value}, not SUCCESS. Only a "
            "successful backup can be restored.",
            code="backup_not_restorable",
        )
    if not record.remote_path:
        raise RestoreError(
            f"Backup #{record.id} has no stored object path.", code="backup_no_path"
        )
    if not record.checksum:
        raise RestoreError(
            f"Backup #{record.id} has no recorded checksum, so its integrity "
            "cannot be established. Refusing to restore unverified data.",
            code="backup_no_checksum",
        )

    downloader = DOWNLOADERS.get(record.provider.value)
    if downloader is None:
        raise RestoreError(
            f"Restoring from {record.provider.value} is not supported.",
            code="provider_unsupported",
        )
    if record.provider.value != "LOCAL" and not backup_service.provider_available(
        record.provider.value
    ):
        raise RestoreError(
            f"{record.provider.value} is not configured on this server, so the "
            "backup cannot be downloaded. The backup is intact; add the "
            "credentials for this provider and try again.",
            code="provider_not_configured",
        )

    try:
        blob = downloader(record.remote_path)
    except RestoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Restore download failed for backup %s: %s", record.id, exc)
        raise RestoreError(
            f"Could not download backup #{record.id}: {type(exc).__name__}.",
            code="download_failed",
        ) from exc

    actual = backup_service.checksum(blob)
    if actual != record.checksum:
        raise RestoreError(
            f"Backup #{record.id} failed its integrity check. The stored copy has "
            "been modified or corrupted since it was written, so it will not be "
            "restored.",
            code="checksum_mismatch",
        )

    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestoreError(
            f"Backup #{record.id} is not valid JSON: {type(exc).__name__}.",
            code="payload_not_json",
        ) from exc

    if not isinstance(payload, dict):
        raise RestoreError(
            f"Backup #{record.id} is not a JSON object.", code="payload_not_object"
        )

    version = payload.get("backup_version")
    if version not in SUPPORTED_VERSIONS:
        raise RestoreError(
            f"Backup #{record.id} uses format version {version!r}, which this "
            f"server does not understand (supported: "
            f"{sorted(SUPPORTED_VERSIONS)}). Upgrade the server or restore an "
            "older backup.",
            code="unsupported_version",
        )

    return payload, actual


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
def _decimal(value: Any, field_name: str, row: int) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RestoreError(
            f"Row {row}: {field_name} is not a valid amount ({value!r}).",
            code="invalid_row",
        ) from exc


def _same_decimal(live: Decimal, backed_up: Any) -> bool:
    """Compare a live amount with a backed-up one, tolerating a malformed value.

    Used only for "does this row already match?" checks during planning, where a
    bad value should mean "cannot confirm it matches" (i.e. an update) rather
    than aborting the whole preview. Malformed values still raise later in
    :func:`apply_restore`, where they would actually corrupt a row.
    """
    try:
        return Decimal(live) == Decimal(str(backed_up))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _datetime(value: Any, field_name: str, row: int) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except (TypeError, ValueError) as exc:
        raise RestoreError(
            f"Row {row}: {field_name} is not a valid timestamp ({value!r}).",
            code="invalid_row",
        ) from exc


def _date(value: Any, field_name: str, row: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise RestoreError(
            f"Row {row}: {field_name} is not a valid date ({value!r}).",
            code="invalid_row",
        ) from exc


def _rows(payload: Dict, key: str) -> List[Dict]:
    value = payload.get(key) or []
    if not isinstance(value, list):
        raise RestoreError(
            f"Backup section {key!r} is not a list.", code="invalid_section"
        )
    return [row for row in value if isinstance(row, dict)]


# ---------------------------------------------------------------------------
# Natural keys
#
# A natural key is what makes a restore idempotent. Primary keys cannot be used:
# the live table's ids belong to whatever the database has since assigned, and
# reusing the backup's ids would either collide or silently point at somebody
# else's row.
# ---------------------------------------------------------------------------
def transaction_key(row: Dict) -> Tuple:
    """Identify a transaction by bank reference, else by a content fingerprint.

    ``bank_reference`` is the bank's own identifier for the transaction and is
    stable across exports, so it is preferred. SMS-imported and manually added
    rows have no reference, so those fall back to a fingerprint of the fields
    that define the transaction. A fingerprint is weaker than a bank reference -
    two genuinely different transactions could match - which is exactly why a
    fingerprint hit with *different* contents is reported as a conflict instead
    of being overwritten.
    """
    reference = (row.get("bank_reference") or "").strip()
    if reference:
        return ("bank_reference", reference)
    return (
        "fingerprint",
        str(row.get("transaction_date") or "")[:19],
        str(row.get("amount") or ""),
        (row.get("category") or "").strip().lower(),
        (row.get("merchant") or "").strip().lower(),
    )


def budget_key(row: Dict) -> Tuple:
    """Mirrors ``uq_budgets_user_category_period``."""
    return (
        (row.get("category") or "").strip().lower(),
        int(row.get("month") or 0),
        int(row.get("year") or 0),
    )


def loan_key(row: Dict) -> Tuple:
    return (
        (row.get("name") or "").strip().lower(),
        (row.get("lender") or "").strip().lower(),
        str(row.get("start_date") or "")[:10],
        str(row.get("principal") or ""),
    )


# ---------------------------------------------------------------------------
# Plan / result model
# ---------------------------------------------------------------------------
@dataclass
class TablePlan:
    name: str
    inserts: int = 0
    updates: int = 0
    skips: int = 0
    conflicts: int = 0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "table": self.name,
            "inserts": self.inserts,
            "updates": self.updates,
            "skips": self.skips,
            "conflicts": self.conflicts,
            "notes": self.notes,
        }


@dataclass
class RestorePlan:
    backup_id: int
    backup_version: int
    generated_at: Optional[str]
    checksum: str
    tables: Dict[str, TablePlan]
    warnings: List[str] = field(default_factory=list)

    @property
    def total_inserts(self) -> int:
        return sum(t.inserts for t in self.tables.values())

    @property
    def total_updates(self) -> int:
        return sum(t.updates for t in self.tables.values())

    @property
    def total_skips(self) -> int:
        return sum(t.skips for t in self.tables.values())

    @property
    def total_conflicts(self) -> int:
        return sum(t.conflicts for t in self.tables.values())

    def as_dict(self) -> Dict:
        return {
            "backup_id": self.backup_id,
            "backup_version": self.backup_version,
            "generated_at": self.generated_at,
            "checksum_verified": True,
            "checksum": self.checksum,
            "tables": [t.as_dict() for t in self.tables.values()],
            "totals": {
                "inserts": self.total_inserts,
                "updates": self.total_updates,
                "skips": self.total_skips,
                "conflicts": self.total_conflicts,
            },
            "warnings": self.warnings,
        }


@dataclass
class RestoreResult:
    plan: RestorePlan
    applied: bool

    def as_dict(self) -> Dict:
        body = self.plan.as_dict()
        body["applied"] = self.applied
        return body


# ---------------------------------------------------------------------------
# Ownership gate
# ---------------------------------------------------------------------------
def _assert_owns_payload(record: BackupRecord, payload: Dict, user_id: int) -> None:
    """Refuse a backup that belongs to a different account.

    Without this, a caller who obtained someone else's backup file could
    replay it into their own account. ``user_id`` is the recorded owner, so the
    only payload that may be written to account ``user_id`` is one that was
    created from that account.
    """
    owner = payload.get("user_id")
    if owner is None:
        raise RestoreError(
            f"Backup #{record.id} does not record which account it belongs to, so "
            "its ownership cannot be verified. Refusing to restore it.",
            code="payload_owner_missing",
        )
    try:
        owner_id = int(owner)
    except (TypeError, ValueError) as exc:
        raise RestoreError(
            f"Backup #{record.id} has a malformed user_id ({owner!r}).",
            code="payload_owner_invalid",
        ) from exc

    if owner_id != user_id:
        # Deliberately the same shape as a missing backup, so this cannot be
        # used to probe whether a given account id has backups.
        raise RestoreError(
            f"Backup #{record.id} was not found.", code="backup_not_found"
        )


def _existing_transactions(db: Session, user_id: int) -> Dict[Tuple, Any]:
    from app.models.transaction import Transaction

    rows = db.execute(
        select(Transaction).where(Transaction.user_id == user_id)
    ).scalars()
    return {transaction_key(_tx_to_dict(r)): r for r in rows}


def _tx_to_dict(row) -> Dict:
    """The natural-key and comparison fields of a live Transaction."""
    return {
        "id": row.id,
        "bank_reference": row.bank_reference,
        "transaction_date": row.transaction_date.isoformat(),
        "amount": str(row.amount),
        "category": row.category,
        "merchant": row.merchant,
    }


def _tx_comparable(row) -> Dict:
    """Live transaction reduced to the fields compared against the backup."""
    live = _tx_to_dict(row)
    return {k: live[k] for k in transaction_key_fields(live)}


def _plan_transactions(
    db: Session, user_id: int, payload: Dict, plan: RestorePlan
) -> Dict[int, Any]:
    """Decide, but do not write, what happens to each backed-up transaction.

    Returns the map ``backup transaction id -> live Transaction`` so fraud
    alerts can be re-pointed at the rows that actually exist afterwards.
    """
    table = plan.tables.setdefault("transactions", TablePlan("transactions"))
    existing = _existing_transactions(db, user_id)
    resolved: Dict[int, Any] = {}

    for index, row in enumerate(_rows(payload, "transactions")):
        key = transaction_key(row)
        current = existing.get(key)
        backup_id = row.get("id")

        if current is None:
            table.inserts += 1
            continue

        if _tx_comparable(current) == transaction_key_fields(row):
            table.skips += 1
            resolved[backup_id] = current
            continue

        # Same key, different contents. For a bank reference that means the
        # bank row changed; for a fingerprint it may just be two different
        # transactions that happen to look alike. Either way, do not guess.
        table.conflicts += 1
        table.notes.append(
            f"Transaction {backup_id} matches an existing row on "
            f"{'bank reference' if key[0] == 'bank_reference' else 'content fingerprint'} "
            "but the details differ; left unchanged."
        )
        resolved[backup_id] = current

    return resolved


def transaction_key_fields(row: Dict) -> Dict:
    """The comparable subset of a transaction row, used for conflict detection."""
    return {
        "bank_reference": row.get("bank_reference"),
        "transaction_date": str(row.get("transaction_date") or "")[:19],
        "amount": str(row.get("amount") or ""),
        "category": row.get("category"),
        "merchant": row.get("merchant"),
    }


def _plan_budgets(db: Session, user_id: int, payload: Dict, plan: RestorePlan) -> None:
    from app.models.budget import Budget

    table = plan.tables.setdefault("budgets", TablePlan("budgets"))
    rows = db.execute(
        select(Budget).where(Budget.user_id == user_id)
    ).scalars()
    existing = {budget_key(_budget_to_dict(r)): r for r in rows}

    for row in _rows(payload, "budgets"):
        key = budget_key(row)
        current = existing.get(key)
        amount = _decimal(row.get("amount"), "amount", 0)
        if current is None:
            table.inserts += 1
        elif current.amount == amount:
            table.skips += 1
        else:
            table.updates += 1


def _budget_to_dict(row) -> Dict:
    return {"category": row.category, "month": row.month, "year": row.year}


def _plan_loans(
    db: Session, user_id: int, payload: Dict, plan: RestorePlan
) -> Tuple[Dict[int, Any], set]:
    """Plan the loans.

    Returns ``(resolved, pending)`` where ``resolved`` maps a backup loan id to
    the live ``Loan`` for loans that already exist, and ``pending`` is the set of
    backup loan ids that will be inserted. Both are needed to plan payments: a
    payment of an existing loan may already be scheduled, while a payment of a
    brand-new loan is guaranteed to be an insert.
    """
    from app.models.loan import Loan

    table = plan.tables.setdefault("loans", TablePlan("loans"))
    rows = db.execute(select(Loan).where(Loan.user_id == user_id)).scalars()
    existing = {loan_key(_loan_to_dict(r)): r for r in rows}
    resolved: Dict[int, Any] = {}
    pending: set = set()

    for row in _rows(payload, "loans"):
        current = existing.get(loan_key(row))
        backup_id = row.get("id")
        if current is None:
            table.inserts += 1
            pending.add(backup_id)
            continue
        resolved[backup_id] = current
        if _same_decimal(current.monthly_emi, row.get("monthly_emi")):
            table.skips += 1
        else:
            table.updates += 1
    return resolved, pending


def _loan_to_dict(row) -> Dict:
    return {
        "name": row.name,
        "lender": row.lender,
        "start_date": row.start_date.isoformat(),
        "principal": str(row.principal),
    }


def _plan_loan_payments(
    db: Session,
    payload: Dict,
    loans: Dict[int, Any],
    pending_loans: set,
    plan: RestorePlan,
) -> None:
    """Plan the repayment schedule against the loans that will exist.

    A payment whose parent loan is not being restored cannot be restored either,
    so those are skipped rather than counted as inserts - otherwise the preview
    would promise rows the apply step silently drops.
    """
    from app.models.loan import LoanPayment

    table = plan.tables.setdefault("loan_payments", TablePlan("loan_payments"))
    seen: Dict[Tuple, int] = {}

    for row in _rows(payload, "loan_payments"):
        installment = int(row.get("installment_number") or 0)
        backup_loan_id = row.get("loan_id")

        if backup_loan_id in pending_loans:
            loan = None  # a new loan, so nothing can already be scheduled
        else:
            loan = loans.get(backup_loan_id)

        if loan is None and backup_loan_id not in pending_loans:
            table.skips += 1
            table.notes.append(
                f"Installment {installment} belongs to loan {backup_loan_id}, "
                "which is not part of this restore, so it was skipped."
            )
            continue

        dedupe_key = (backup_loan_id, installment)
        if dedupe_key in seen:
            table.conflicts += 1
            table.notes.append(
                f"Installment {installment} of loan {backup_loan_id} appears "
                f"{seen[dedupe_key] + 1} times in the backup; only the first will "
                "be restored."
            )
            continue
        seen[dedupe_key] = 1

        if loan is None:
            table.inserts += 1
            continue

        already = db.execute(
            select(LoanPayment).where(
                LoanPayment.loan_id == loan.id,
                LoanPayment.installment_number == installment,
            )
        ).scalar_one_or_none()
        if already is None:
            table.inserts += 1
        else:
            table.skips += 1


def _plan_fraud_alerts(
    db: Session, user_id: int, payload: Dict, transactions: Dict[int, Any], plan: RestorePlan
) -> None:
    from app.models.fraud_alert import FraudAlert

    table = plan.tables.setdefault("fraud_alerts", TablePlan("fraud_alerts"))

    live = db.execute(
        select(FraudAlert).where(FraudAlert.user_id == user_id)
    ).scalars()
    existing = {fraud_alert_key(r): r for r in live}

    for row in _rows(payload, "fraud_alerts"):
        transaction = transactions.get(row.get("transaction_id"))
        if transaction is None:
            # Unattached in the backup, or its transaction is not being
            # restored. Either way there is nothing to attach it to.
            table.skips += 1
            table.notes.append(
                f"Fraud alert for transaction {row.get('transaction_id')} cannot be "
                "re-linked (the transaction is not part of this restore) and will "
                "be skipped."
            )
            continue
        if fraud_alert_key_from_row(row, transaction.id) in existing:
            table.skips += 1
        else:
            table.inserts += 1


def fraud_alert_key(row) -> Tuple:
    return (row.transaction_id, row.risk_score, row.detection_layer)


def fraud_alert_key_from_row(row: Dict, transaction_id: int) -> Tuple:
    return (transaction_id, int(row.get("risk_score") or 0), row.get("detection_layer"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def plan_restore(db: Session, record: BackupRecord, user_id: int) -> RestorePlan:
    """Compute what a restore *would* do. Performs no writes and no commit."""
    payload, actual = fetch_and_verify(record)
    _assert_owns_payload(record, payload, user_id)

    plan = RestorePlan(
        backup_id=record.id,
        backup_version=payload.get("backup_version"),
        generated_at=payload.get("generated_at"),
        checksum=actual,
        tables={},
    )

    transactions = _plan_transactions(db, user_id, payload, plan)
    _plan_budgets(db, user_id, payload, plan)
    loans, pending_loans = _plan_loans(db, user_id, payload, plan)
    _plan_loan_payments(db, payload, loans, pending_loans, plan)
    _plan_fraud_alerts(db, user_id, payload, transactions, plan)

    if plan.total_conflicts:
        plan.warnings.append(
            f"{plan.total_conflicts} row(s) matched an existing record on its "
            "natural key but differed in content. They will be left unchanged "
            "rather than overwritten."
        )
    if plan.total_inserts:
        plan.warnings.append(
            f"{plan.total_inserts} row(s) will be inserted with new primary keys. "
            "Any external reference to the old ids will not resolve."
        )
    if not plan.tables:
        plan.warnings.append("This backup contains no restorable rows.")

    return plan


def _apply_transactions(
    db: Session, user_id: int, payload: Dict, existing: Dict[Tuple, Any]
) -> Dict[int, Any]:
    from app.models.transaction import Transaction

    resolved: Dict[int, Any] = {}
    for index, row in enumerate(_rows(payload, "transactions")):
        key = transaction_key(row)
        current = existing.get(key)
        backup_id = row.get("id")
        if current is not None:
            resolved[backup_id] = current
            continue

        current = Transaction(
            user_id=user_id,
            transaction_type=row.get("transaction_type") or "expense",
            amount=_decimal(row.get("amount"), "amount", index),
            category=row.get("category") or "Uncategorized",
            emi_type=row.get("emi_type"),
            merchant=row.get("merchant"),
            description=row.get("description"),
            transaction_date=_datetime(
                row.get("transaction_date"), "transaction_date", index
            ),
            source=row.get("source") or "MANUAL",
            bank_reference=row.get("bank_reference"),
            fraud_score=row.get("fraud_score"),
            is_flagged=bool(row.get("is_flagged")),
        )
        db.add(current)
        db.flush()  # assigns the real id for child rows
        existing[key] = current
        resolved[backup_id] = current
    return resolved


def _apply_budgets(db: Session, user_id: int, payload: Dict) -> None:
    from app.models.budget import Budget

    rows = db.execute(select(Budget).where(Budget.user_id == user_id)).scalars()
    existing = {budget_key(_budget_to_dict(r)): r for r in rows}

    for index, row in enumerate(_rows(payload, "budgets")):
        key = budget_key(row)
        amount = _decimal(row.get("amount"), "amount", index)
        current = existing.get(key)
        if current is None:
            added = Budget(
                user_id=user_id,
                category=row.get("category") or "Uncategorized",
                amount=amount,
                month=key[1],
                year=key[2],
            )
            db.add(added)
            existing[key] = added
        elif current.amount != amount:
            current.amount = amount


def _apply_loans(db: Session, user_id: int, payload: Dict) -> Dict[int, Any]:
    from app.models.loan import Loan

    rows = db.execute(select(Loan).where(Loan.user_id == user_id)).scalars()
    existing = {loan_key(_loan_to_dict(r)): r for r in rows}

    resolved: Dict[int, Any] = {}
    for index, row in enumerate(_rows(payload, "loans")):
        key = loan_key(row)
        backup_id = row.get("id")
        current = existing.get(key)
        if current is None:
            current = Loan(
                user_id=user_id,
                name=row.get("name") or "Restored loan",
                lender=row.get("lender"),
                loan_type=row.get("loan_type") or "PERSONAL",
                principal=_decimal(row.get("principal"), "principal", index),
                interest_rate=_decimal(
                    row.get("interest_rate", "0"), "interest_rate", index
                ),
                tenure_months=int(row.get("tenure_months") or 0),
                monthly_emi=_decimal(row.get("monthly_emi"), "monthly_emi", index),
                total_payable=_decimal(
                    row.get("total_payable"), "total_payable", index
                ),
                start_date=_date(row.get("start_date"), "start_date", index),
                status=row.get("status") or "ACTIVE",
            )
            db.add(current)
            db.flush()
            existing[key] = current
        else:
            emi = _decimal(row.get("monthly_emi"), "monthly_emi", index)
            if current.monthly_emi != emi:
                current.monthly_emi = emi
                current.status = row.get("status") or current.status
        resolved[backup_id] = current
    return resolved


def _apply_loan_payments(
    db: Session, user_id: int, payload: Dict, loans: Dict[int, Any]
) -> None:
    from app.models.loan import LoanPayment

    for index, row in enumerate(_rows(payload, "loan_payments")):
        loan = loans.get(row.get("loan_id"))
        if loan is None:
            # The parent loan was not in the backup or was not restored; a
            # payment cannot exist without it, and inventing one would be wrong.
            continue
        already = db.execute(
            select(LoanPayment).where(
                LoanPayment.loan_id == loan.id,
                LoanPayment.installment_number == int(row.get("installment_number") or 0),
            )
        ).scalar_one_or_none()
        if already is not None:
            continue
        db.add(
            LoanPayment(
                loan_id=loan.id,
                user_id=user_id,
                installment_number=int(row.get("installment_number") or 0),
                amount=_decimal(row.get("amount"), "amount", index),
                due_date=_date(row.get("due_date"), "due_date", index),
                paid_date=(
                    _date(row.get("paid_date"), "paid_date", index)
                    if row.get("paid_date")
                    else None
                ),
                status=row.get("status") or "PENDING",
            )
        )


def _apply_fraud_alerts(
    db: Session, user_id: int, payload: Dict, transactions: Dict[int, Any]
) -> None:
    from app.models.fraud_alert import FraudAlert

    for index, row in enumerate(_rows(payload, "fraud_alerts")):
        transaction = transactions.get(row.get("transaction_id"))
        if transaction is None:
            # Either the alert was unattached, or its transaction is not being
            # restored. Skip rather than store an alert with a dangling link.
            continue
        db.add(
            FraudAlert(
                user_id=user_id,
                transaction_id=transaction.id,
                risk_score=int(row.get("risk_score") or 0),
                risk_level=row.get("risk_level") or "LOW",
                is_fraud=bool(row.get("is_fraud")),
                detection_layer=row.get("detection_layer") or "RULES",
                reasons=row.get("reasons"),
                amount_snapshot=transaction.amount,
                merchant_snapshot=transaction.merchant,
                category_snapshot=transaction.category,
            )
        )


def apply_restore(db: Session, record: BackupRecord, user_id: int) -> RestoreResult:
    """Upsert the backup into the account, inside a single transaction.

    The caller must have shown the caller-facing preview first; this function
    re-plans from scratch (so the decision is always made against current data)
    and commits only when every section applied cleanly. Any error rolls the
    whole thing back - a half-restored ledger is worse than an unrestored one.
    """
    plan = plan_restore(db, record, user_id)
    payload, _ = fetch_and_verify(record)

    try:
        existing = _existing_transactions(db, user_id)
        transactions = _apply_transactions(db, user_id, payload, existing)
        _apply_budgets(db, user_id, payload)
        loans = _apply_loans(db, user_id, payload)
        _apply_loan_payments(db, user_id, payload, loans)
        _apply_fraud_alerts(db, user_id, payload, transactions)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Restore of backup %s failed and was rolled back", record.id)
        raise

    return RestoreResult(plan=plan, applied=True)
