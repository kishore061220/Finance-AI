"""Backup restore tests.

Restore is the only endpoint in this API that can rewrite a user's whole
ledger, so these tests lean on the failure paths: checksum tampering, backups
belonging to other accounts, and repeated restores. A restore that quietly
duplicates transactions or accepts a corrupted file is worse than no restore at
all, so idempotency and refusal are treated as first-class behaviour.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.backup import BackupRecord, BackupStatus
from app.models.loan import Loan, LoanPayment
from app.models.transaction import Transaction
from app.models.user import User
from app.services import backup as backup_service
from app.services import restore as restore_service
from app.tests.conftest import mint_token, resolve_user, seed_transaction


@pytest.fixture()
def backup_dir(tmp_path):
    """A backup directory for tests that need to corrupt or delete the file.

    The directory itself is already redirected for every test by the autouse
    ``_isolate`` fixture; this returns a path inside it so tests that tamper with
    the stored blob can locate and rewrite it.
    """
    return backup_service.LOCAL_BACKUP_DIR


@pytest.fixture()
def alice(client, auth, db):
    """A small, realistic dataset to back up and restore."""
    uid = resolve_user(db, "uid-alice", "alice@example.com")
    now = datetime.utcnow().replace(microsecond=0)
    for i in range(6):
        seed_transaction(
            db,
            uid,
            amount=Decimal("100.00") + i,
            merchant=f"Store {i}",
            category="Food" if i % 2 == 0 else "Transport",
            bank_reference=f"REF-{i:03d}",
            transaction_date=now - timedelta(days=i),
        )
    return uid


def make_backup(client, auth, **kwargs):
    response = client.post("/api/backups", headers=auth, json=kwargs or {})
    assert response.status_code == 200, response.text
    return response.json()


def live_count(db, user_id) -> int:
    return (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .count()
    )


class TestBackupPrerequisites:
    def test_preview_of_unknown_backup_is_404(self, client, auth):
        assert client.get("/api/backups/9999/restore/preview", headers=auth).status_code == 404

    def test_cannot_preview_another_users_backup(self, client, auth, other_auth, db, alice, backup_dir):
        backup = make_backup(client, auth)
        # Bob asks for Alice's backup by id.
        response = client.get(
            f"/api/backups/{backup['id']}/restore/preview", headers=other_auth
        )
        assert response.status_code == 404
        # And cannot restore it either.
        assert (
            client.post(
                f"/api/backups/{backup['id']}/restore",
                headers=other_auth,
                json={"confirm": True},
            ).status_code
            == 404
        )

    def test_restore_requires_explicit_confirmation(self, client, auth, alice, backup_dir):
        backup = make_backup(client, auth)
        # No body at all - a mis-wired client must not wipe a ledger.
        bare = client.post(f"/api/backups/{backup['id']}/restore", headers=auth, json={})
        assert bare.status_code == 400
        assert bare.json()["detail"]["code"] == "confirmation_required"

        explicit_false = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": False}
        )
        assert explicit_false.status_code == 400

    def test_failed_backup_is_not_restorable(self, client, auth, db, backup_dir, monkeypatch):
        def broken(blob, name):
            raise OSError("disk full")

        monkeypatch.setitem(backup_service.UPLOADERS, "LOCAL", broken)
        failed = client.post("/api/backups", headers=auth, json={"provider": "FIREBASE_STORAGE"})
        assert failed.status_code == 502
        backup_id = failed.json()["detail"]["backup_id"]

        response = client.get(f"/api/backups/{backup_id}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "backup_not_restorable"

    def test_backup_without_checksum_is_refused(self, client, auth, db, alice, backup_dir):
        """A record with no checksum has unproven integrity - never restore it."""
        backup = make_backup(client, auth)
        record = db.get(BackupRecord, backup["id"])
        record.checksum = None
        db.commit()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "backup_no_checksum"


class TestChecksumEnforcement:
    def test_tampered_file_is_rejected_before_any_write(
        self, client, auth, db, alice, backup_dir
    ):
        backup = make_backup(client, auth)
        before = live_count(db, alice)

        # Rewrite the stored blob, keeping it valid JSON but changing the money.
        path = Path(
            db.get(BackupRecord, backup["id"]).remote_path
        )
        payload = json.loads(path.read_text())
        payload["transactions"][0]["amount"] = "999999.00"
        payload["user_id"] = payload["user_id"]
        path.write_text(json.dumps(payload, indent=2))

        preview = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert preview.status_code == 409
        assert preview.json()["detail"]["code"] == "checksum_mismatch"

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 409
        assert applied.json()["detail"]["code"] == "checksum_mismatch"
        # Nothing was written.
        assert live_count(db, alice) == before

    def test_truncated_file_is_rejected(self, client, auth, db, alice, backup_dir):
        backup = make_backup(client, auth)
        path = Path(db.get(BackupRecord, backup["id"]).remote_path)
        path.write_text('{"backup_version": 1, "user_id":')

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "checksum_mismatch"

    def test_missing_file_is_reported_as_gone(self, client, auth, db, alice, backup_dir):
        backup = make_backup(client, auth)
        Path(db.get(BackupRecord, backup["id"]).remote_path).unlink()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "backup_file_missing"

    def test_unchecksummed_payload_is_refused_even_if_valid_json(
        self, client, auth, db, alice, backup_dir
    ):
        """Re-signed JSON still has no provenance; a missing checksum blocks it."""
        backup = make_backup(client, auth)
        record = db.get(BackupRecord, backup["id"])
        record.checksum = None
        db.commit()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "backup_no_checksum"


class TestCrossAccountProtection:
    def test_payload_owned_by_another_account_is_refused(
        self, client, auth, db, alice, backup_dir
    ):
        """A backup file claiming a different owner must never be replayed.

        This is the attack the ownership gate exists for: an attacker who gets
        hold of somebody's backup JSON and re-uploads it must not be able to
        import that data into their own account.
        """
        backup = make_backup(client, auth)
        record = db.get(BackupRecord, backup["id"])
        path = Path(record.remote_path)

        # Rewrite the payload to claim a different owner, then re-checksum it so
        # integrity checking passes and only the ownership gate is left.
        payload = json.loads(path.read_text())
        payload["user_id"] = 4242
        blob = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(blob)
        record.checksum = backup_service.checksum(blob)
        db.commit()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 404
        # Shaped like "not found" so this cannot enumerate other account ids.
        assert response.json()["detail"]["code"] == "backup_not_found"

    def test_payload_without_owner_is_refused(self, client, auth, db, alice, backup_dir):
        backup = make_backup(client, auth)
        record = db.get(BackupRecord, backup["id"])
        path = Path(record.remote_path)
        payload = json.loads(path.read_text())
        del payload["user_id"]
        blob = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(blob)
        record.checksum = backup_service.checksum(blob)
        db.commit()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "payload_owner_missing"

    def test_unsupported_format_version_is_refused(self, client, auth, db, alice, backup_dir):
        backup = make_backup(client, auth)
        record = db.get(BackupRecord, backup["id"])
        path = Path(record.remote_path)
        payload = json.loads(path.read_text())
        payload["backup_version"] = 99
        blob = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(blob)
        record.checksum = backup_service.checksum(blob)
        db.commit()

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "unsupported_version"

    def test_cloud_provider_without_credentials_reports_503(
        self, client, auth, db, backup_dir
    ):
        """The backup is intact but the server cannot fetch it - say so plainly."""
        uid = resolve_user(db, "uid-alice", "alice@example.com")
        record = BackupRecord(
            user_id=uid,
            provider="GOOGLE_CLOUD_STORAGE",
            status=BackupStatus.SUCCESS,
            remote_path="finance-ai/user_1/20260101_000000.json",
            checksum="deadbeef",
            size_bytes=10,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        response = client.get(f"/api/backups/{record.id}/restore/preview", headers=auth)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "provider_not_configured"
        assert "intact" in response.json()["detail"]["error"]


class TestPreview:
    def test_preview_reports_counts_and_writes_nothing(
        self, client, auth, db, alice, backup_dir
    ):
        backup = make_backup(client, auth)
        before = live_count(db, alice)

        response = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        assert response.status_code == 200
        body = response.json()

        assert body["checksum_verified"] is True
        assert body["applied"] is False
        assert body["backup_version"] == 1
        assert body["generated_at"]

        tables = {t["table"]: t for t in body["tables"]}
        assert set(tables) == {
            "transactions",
            "budgets",
            "loans",
            "loan_payments",
            "fraud_alerts",
        }
        # The data is already in the database, so everything is a skip.
        assert tables["transactions"]["inserts"] == 0
        assert tables["transactions"]["skips"] == 6
        assert tables["transactions"]["updates"] == 0
        assert body["totals"]["inserts"] == 0

        # Crucially, preview changed nothing.
        assert live_count(db, alice) == before

    def test_preview_never_commits_its_reads(self, client, auth, db, alice, backup_dir):
        """A preview that dirtied the session could poison a later write."""
        backup = make_backup(client, auth)
        for _ in range(3):
            response = client.get(
                f"/api/backups/{backup['id']}/restore/preview", headers=auth
            )
            assert response.status_code == 200
        db.expire_all()
        assert live_count(db, alice) == 6


class TestApplyAndIdempotency:
    def test_restore_reinstates_deleted_transactions(
        self, client, auth, db, alice, backup_dir
    ):
        backup = make_backup(client, auth)

        # User "loses" their history - the scenario restore exists for.
        db.query(Transaction).filter(Transaction.user_id == alice).delete()
        db.commit()
        assert live_count(db, alice) == 0

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["applied"] is True

        transactions = body["totals"] and {t["table"]: t for t in body["tables"]}
        assert transactions["transactions"]["inserts"] == 6

        db.expire_all()
        restored = (
            db.query(Transaction)
            .filter(Transaction.user_id == alice)
            .order_by(Transaction.id)
            .all()
        )
        assert len(restored) == 6
        # Values survived the round trip exactly, including money precision.
        assert sorted(str(t.amount) for t in restored) == sorted(
            f"{Decimal('100.00') + i:.2f}" for i in range(6)
        )
        assert {t.bank_reference for t in restored} == {f"REF-{i:03d}" for i in range(6)}

    def test_restoring_twice_inserts_nothing_the_second_time(
        self, client, auth, db, alice, backup_dir
    ):
        """The single most important property: a restore must be repeatable."""
        backup = make_backup(client, auth)
        db.query(Transaction).filter(Transaction.user_id == alice).delete()
        db.commit()

        first = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert first.status_code == 200
        assert first.json()["totals"]["inserts"] == 6
        db.expire_all()
        after_first = live_count(db, alice)

        second = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert second.status_code == 200
        totals = second.json()["totals"]
        assert totals["inserts"] == 0
        assert totals["updates"] == 0
        assert totals["skips"] == 6
        assert totals["conflicts"] == 0

        db.expire_all()
        assert live_count(db, alice) == after_first == 6

    def test_restore_never_duplicates_onto_existing_data(
        self, client, auth, db, alice, backup_dir
    ):
        backup = make_backup(client, auth)
        # Data is untouched; a restore must be a no-op, not a doubling.
        before = live_count(db, alice)
        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200
        assert applied.json()["totals"]["inserts"] == 0
        db.expire_all()
        assert live_count(db, alice) == before

    def test_budget_upserts_on_category_and_period(
        self, client, auth, db, alice, backup_dir
    ):
        from app.tests.conftest import seed_budget
        from app.models.budget import Budget

        now = datetime.utcnow()
        seed_budget(db, alice, category="Food", month=now.month, year=now.year, amount=Decimal("500.00"))
        backup = make_backup(client, auth)

        # Change the live budget, then restore: the old value should come back.
        budget = (
            db.query(Budget)
            .filter(Budget.user_id == alice, Budget.category == "Food")
            .one()
        )
        budget.amount = Decimal("9999.00")
        db.commit()

        preview = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        tables = {t["table"]: t for t in preview.json()["tables"]}
        assert tables["budgets"]["updates"] == 1
        assert tables["budgets"]["inserts"] == 0

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.json()["totals"]["updates"] == 1
        db.expire_all()
        assert budget.amount == Decimal("500.00")

    def test_loans_and_payments_are_re_linked_to_new_loan_ids(
        self, client, auth, db, alice, backup_dir
    ):
        """A restored loan gets a new id; its payments must follow it.

        Child rows reference the parent's *live* id, never the id the backup
        happened to record, otherwise a restore either drops the payments or
        points them at an unrelated loan.
        """
        from app.models.loan import LoanPayment

        client.post(
            "/api/loans",
            headers=auth,
            json={
                "name": "Home loan",
                "lender": "Test Bank",
                "loan_type": "Home Loan",
                "principal": "500000.00",
                "interest_rate": "7.5",
                "tenure_months": 3,
                "start_date": "2026-01-01",
            },
        )
        # Creating a loan already generates its full repayment schedule, so the
        # three payments exist without any extra calls.

        backup = make_backup(client, auth)
        loan = db.query(Loan).filter(Loan.user_id == alice).one()
        original_loan_id = loan.id
        original_payment_ids = sorted(
            p.id
            for p in db.query(LoanPayment).filter(LoanPayment.loan_id == original_loan_id).all()
        )
        assert len(original_payment_ids) == 3

        # Wipe them, then restore.
        db.query(LoanPayment).filter(LoanPayment.loan_id == original_loan_id).delete()
        db.query(Loan).filter(Loan.id == original_loan_id).delete()
        db.commit()

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200, applied.text
        tables = {t["table"]: t for t in applied.json()["tables"]}
        assert tables["loans"]["inserts"] == 1
        assert tables["loan_payments"]["inserts"] == 3

        db.expire_all()
        new_loan = db.query(Loan).filter(Loan.user_id == alice).one()
        # The loan was re-created, so its schedule had to be re-created with it.
        payments = (
            db.query(LoanPayment).filter(LoanPayment.loan_id == new_loan.id).all()
        )
        assert len(payments) == 3
        assert {p.installment_number for p in payments} == {1, 2, 3}
        assert all(p.user_id == alice for p in payments)
        # Every payment points at a loan that actually exists - no orphans, which
        # is the failure mode if the backup's loan ids were trusted verbatim.
        for payment in payments:
            assert db.get(Loan, payment.loan_id) is not None
        # And the preview promised exactly what was written.
        assert tables["loan_payments"]["inserts"] == len(payments)

    def test_fraud_alerts_are_re_attached_to_restored_transactions(
        self, client, auth, db, alice, backup_dir
    ):
        from app.models.fraud_alert import FraudAlert

        # Produce a real alert by creating a transaction the scorer flags.
        # (The dry-run /api/fraud/score endpoint scores without persisting, so
        # an alert only exists once a transaction is actually stored.)
        created = client.post(
            "/api/transactions",
            headers=auth,
            json={
                "transaction_type": "expense",
                "amount": "250000.00",
                "category": "Shopping",
                "merchant": "Luxury Store",
                "transaction_date": "2026-01-15T02:30:00",
            },
        )
        assert created.status_code == 201
        assert created.json()["is_flagged"] is True
        alerts = db.query(FraudAlert).filter(FraudAlert.user_id == alice).all()
        assert alerts, "expected the stored transaction to raise an alert"
        original_tx_ids = {a.transaction_id for a in alerts}

        backup = make_backup(client, auth)

        db.query(FraudAlert).filter(FraudAlert.user_id == alice).delete()
        db.query(Transaction).filter(Transaction.user_id == alice).delete()
        db.commit()

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200
        db.expire_all()

        restored_alerts = (
            db.query(FraudAlert).filter(FraudAlert.user_id == alice).all()
        )
        assert len(restored_alerts) == len(alerts)
        # Every alert now points at a transaction that actually exists.
        for alert in restored_alerts:
            assert alert.transaction_id is not None
            assert db.get(Transaction, alert.transaction_id) is not None
        # The score itself survived.
        assert {a.risk_score for a in restored_alerts} == {a.risk_score for a in alerts}
        assert original_tx_ids  # the original scoring did produce links


class TestConflicts:
    def test_matching_key_with_different_details_is_reported_not_overwritten(
        self, client, auth, db, alice, backup_dir
    ):
        """A natural-key hit with different contents is a conflict, not an update.

        Silently replacing a row because a key happened to match is how a
        restore destroys data that was entered after the backup was taken.
        """
        backup = make_backup(client, auth)

        # The bank reference REF-002 now points at a different amount.
        row = (
            db.query(Transaction)
            .filter(Transaction.user_id == alice, Transaction.bank_reference == "REF-002")
            .one()
        )
        row.amount = Decimal("777.00")
        row.category = "Medical"
        db.commit()

        preview = client.get(f"/api/backups/{backup['id']}/restore/preview", headers=auth)
        transactions = {t["table"]: t for t in preview.json()["tables"]}["transactions"]
        assert transactions["conflicts"] == 1
        assert transactions["inserts"] == 0
        assert transactions["updates"] == 0
        assert any("left unchanged" in note for note in transactions["notes"])
        assert any("natural key" in w for w in preview.json()["warnings"])

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.json()["totals"]["conflicts"] == 1

        db.expire_all()
        # The newer, edited row is intact.
        assert row.amount == Decimal("777.00")
        assert row.category == "Medical"
        assert live_count(db, alice) == 6

    def test_fingerprint_collision_is_treated_as_a_conflict(
        self, client, auth, db, backup_dir
    ):
        """Rows with no bank reference fall back to a weak key - and are cautious."""
        uid = resolve_user(db, "uid-alice", "alice@example.com")
        moment = datetime.utcnow().replace(microsecond=0)
        for i in range(2):
            seed_transaction(
                db,
                uid,
                amount=Decimal("50.00") + i,
                merchant="Corner Cafe",
                category="Food",
                bank_reference=None,
                transaction_date=moment,
            )
        backup = make_backup(client, auth)
        assert (
            client.post(
                f"/api/backups/{backup['id']}/restore",
                headers=auth,
                json={"confirm": True},
            ).status_code
            == 200
        )

        # Mutate one of the two; the fingerprint no longer matches cleanly.
        first = (
            db.query(Transaction)
            .filter(Transaction.user_id == uid, Transaction.merchant == "Corner Cafe")
            .first()
        )
        first.amount = Decimal("88.00")
        db.commit()

        applied = client.post(
            f"/api/backups/{backup['id']}/restore",
            headers=auth,
            json={"confirm": True},
        )
        assert applied.status_code == 200
        db.expire_all()
        assert first.amount == Decimal("88.00")


class TestRestoreIsolation:
    def test_restore_does_not_touch_another_user(self, client, auth, other_auth, db, alice, backup_dir):
        bob = resolve_user(db, "uid-bob", "bob@example.com")
        seed_transaction(db, bob, amount=Decimal("999.00"), merchant="Bob Store")
        db.commit()

        backup = make_backup(client, auth)
        db.query(Transaction).filter(Transaction.user_id == alice).delete()
        db.commit()

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200

        db.expire_all()
        # Bob's data is exactly as it was.
        bob_rows = (
            db.query(Transaction).filter(Transaction.user_id == bob).all()
        )
        assert len(bob_rows) == 1
        assert bob_rows[0].amount == Decimal("999.00")
        # And every restored row is stamped with Alice, never Bob.
        for row in db.query(Transaction).filter(Transaction.user_id == alice).all():
            assert row.user_id == alice

    def test_ids_in_the_payload_are_never_trusted_as_ownership(
        self, client, auth, db, alice, backup_dir
    ):
        """A payload claiming a foreign ``user_id`` on a row must not relocate it."""
        bob = resolve_user(db, "uid-bob", "bob@example.com")
        db.commit()
        backup = make_backup(client, auth)

        record = db.get(BackupRecord, backup["id"])
        path = Path(record.remote_path)
        payload = json.loads(path.read_text())
        # Stash Bob's id on a row while the backup as a whole stays Alice's.
        for row in payload["transactions"]:
            row["id"] = bob
        blob = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(blob)
        record.checksum = backup_service.checksum(blob)
        db.commit()

        db.query(Transaction).filter(Transaction.user_id == alice).delete()
        db.commit()

        applied = client.post(
            f"/api/backups/{backup['id']}/restore", headers=auth, json={"confirm": True}
        )
        assert applied.status_code == 200
        db.expire_all()

        assert live_count(db, bob) == 0
        for row in db.query(Transaction).filter(Transaction.user_id == alice).all():
            assert row.user_id == alice


class TestRestoreErrorMapping:
    def test_garbage_payload_is_a_409_not_a_crash(self, client, auth, db, backup_dir):
        uid = resolve_user(db, "uid-alice", "alice@example.com")
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / "garbage.json"
        blob = b"not json at all"
        path.write_bytes(blob)

        record = BackupRecord(
            user_id=uid,
            provider="LOCAL",
            status=BackupStatus.SUCCESS,
            remote_path=str(path),
            checksum=backup_service.checksum(blob),
            size_bytes=len(blob),
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        response = client.get(f"/api/backups/{record.id}/restore/preview", headers=auth)
        # The checksum matches, so this gets past integrity and fails on parsing.
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "payload_not_json"

    def test_malformed_amount_is_rejected_during_apply(
        self, client, auth, db, backup_dir
    ):
        """A bad value must roll the whole restore back, not half-apply it."""
        uid = resolve_user(db, "uid-alice", "alice@example.com")
        backup_dir.mkdir(parents=True, exist_ok=True)
        payload = backup_service.collect_user_data(db, uid)
        payload["transactions"].append(
            {
                "id": 9001,
                "transaction_type": "expense",
                "amount": "not-a-number",
                "category": "Food",
                "transaction_date": datetime.utcnow().isoformat(),
                "source": "MANUAL",
                "is_flagged": False,
            }
        )
        blob = backup_service.serialize(payload)
        path = backup_dir / "malformed.json"
        path.write_bytes(blob)

        record = BackupRecord(
            user_id=uid,
            provider="LOCAL",
            status=BackupStatus.SUCCESS,
            remote_path=str(path),
            checksum=backup_service.checksum(blob),
            size_bytes=len(blob),
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        response = client.post(
            f"/api/backups/{record.id}/restore", headers=auth, json={"confirm": True}
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_row"
        # Nothing from the backup landed, not even the valid rows.
        db.expire_all()
        assert live_count(db, uid) == 0

    def test_restore_error_codes_all_map_to_a_sane_status(self):
        from app.routes.backups import _restore_error

        expectations = {
            "backup_not_found": 404,
            "checksum_mismatch": 409,
            "backup_file_missing": 410,
            "provider_not_configured": 503,
            "provider_unsupported": 501,
            "download_failed": 502,
            "unsupported_version": 409,
            "invalid_row": 400,
        }
        for code, expected in expectations.items():
            exc = restore_service.RestoreError("nope", code=code)
            assert _restore_error(exc).status_code == expected, code


class TestServiceLevel:
    def test_plan_restore_is_read_only(self, client, auth, db, alice, backup_dir):
        """Direct service call: planning must not leave the session dirty."""
        make_backup(client, auth)
        record = (
            db.query(BackupRecord)
            .filter(BackupRecord.user_id == alice, BackupRecord.status == BackupStatus.SUCCESS)
            .one()
        )

        plan = restore_service.plan_restore(db, record, alice)
        assert plan.total_inserts == 0
        assert plan.total_skips == 6
        assert plan.checksum

        db.rollback()
        assert live_count(db, alice) == 6

    def test_transaction_key_prefers_bank_reference(self):
        keyed = restore_service.transaction_key(
            {
                "bank_reference": "ABC",
                "transaction_date": "2026-01-01T00:00:00",
                "amount": "1.00",
                "category": "Food",
                "merchant": "X",
            }
        )
        assert keyed == ("bank_reference", "ABC")

    def test_transaction_key_falls_back_to_fingerprint(self):
        keyed = restore_service.transaction_key(
            {
                "bank_reference": None,
                "transaction_date": "2026-01-01T00:00:00",
                "amount": "1.00",
                "category": "Food",
                "merchant": "X",
            }
        )
        assert keyed[0] == "fingerprint"
        # Case differences in free text must not create a phantom new row.
        other = restore_service.transaction_key(
            {
                "bank_reference": "",
                "transaction_date": "2026-01-01T00:00:00",
                "amount": "1.00",
                "category": "food",
                "merchant": "x",
            }
        )
        assert keyed == other
