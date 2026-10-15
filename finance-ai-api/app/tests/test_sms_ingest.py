"""SMS auto-ingestion end-to-end tests.

These drive the real route + real dependency chain against an in-memory
database. They verify the ingest contract:

* usable messages are saved as owned transactions (source=SMS) in one call;
* unusable/OTP/promo/balance-only messages are never imported;
* low-confidence messages wait as PENDING_REVIEW until the owner decides;
* replays and duplicate bodies map to one outcome (idempotency + dedup);
* ERROR rows can be retried with the same client_msg_id;
* no cross-user data is reachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import sms_parser as sms_parser_module

DEBIT_SMS = (
    "Your A/c XX1234 is debited by Rs.1,234.56 on 05-Mar-2026 for SWIGGY "
    "via UPI Ref 123456789012. Avl Bal: Rs 9,000.00"
)
CREDIT_SMS = (
    "Rs 5000.00 credited to your account XX4321 on 05-Mar-2026 "
    "ref No 998877665544. Avl Bal: Rs 10,000.00"
)
OTP_SMS = "Your OTP for HDFC Bank is 453812. Do not share with anyone."
PROMO_SMS = "Get 30% off on your next order! Use code SAVE30. Shop now at store.com"
BALANCE_ONLY_SMS = "Your a/c XX1234 A/c Bal is Rs.1,000.00 on 05-Mar-2026"
LOW_CONFIDENCE_SMS = "Your a/c is debited by Rs.10.00"
GARBAGE_SMS = "qwerty 12345 something totally unrelated"

VALID = {"client_msg_id": "msg-1", "body": DEBIT_SMS}


class TestUnusableMessagesAreNeverImported:
    def test_otp_is_invalid(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "otp-1", "sender": "VM-BHL", "body": OTP_SMS},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "INVALID"
        assert body["transaction_id"] is None
        assert float(client.get("/api/dashboard/summary", headers=auth).json()["expense"]) == 0

    def test_promo_is_invalid(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "promo-1", "body": PROMO_SMS},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "INVALID"

    def test_balance_only_is_invalid(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "bal-1", "body": BALANCE_ONLY_SMS},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "INVALID"

    def test_garbage_is_invalid(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "garbage-1", "body": GARBAGE_SMS},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "INVALID"


class TestUsableMessagesAutoSave:
    def test_debit_is_saved_as_a_transaction(self, client, auth):
        response = client.post("/api/sms/messages", headers=auth, json=VALID)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "SAVED"

        transaction = body["transaction"]
        assert transaction["user_id"] == client.get("/api/auth/me", headers=auth).json()["id"]
        assert transaction["source"] == "SMS"
        assert transaction["transaction_type"] == "expense"
        assert float(transaction["amount"]) == 1234.56
        assert transaction["bank_reference"] == "123456789012"
        assert transaction["id"] is not None
        assert float(transaction["fraud_score"]) >= 0

    def test_credit_is_saved_as_income(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "credit-1", "body": CREDIT_SMS},
        )
        assert response.status_code == 201
        transaction = response.json()["transaction"]
        assert transaction["transaction_type"] == "income"
        assert float(transaction["amount"]) == 5000.00


class TestPendingReviewLifecycle:
    def test_low_confidence_wait_for_review(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-1", "body": LOW_CONFIDENCE_SMS},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "PENDING_REVIEW"
        assert body["transaction_id"] is None
        assert body["transaction"] is None

    def test_confirm_writes_the_transaction(self, client, auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-2", "body": LOW_CONFIDENCE_SMS},
        ).json()["id"]

        confirmed = client.post(f"/api/sms/messages/{message_id}/confirm", headers=auth)
        assert confirmed.status_code == 200
        body = confirmed.json()
        assert body["status"] == "SAVED"
        assert body["transaction"]["transaction_type"] == "expense"
        assert body["transaction"]["source"] == "SMS"

        # Confirming again is a no-op, returns the same saved message.
        again = client.post(f"/api/sms/messages/{message_id}/confirm", headers=auth)
        assert again.status_code == 200
        assert again.json()["transaction_id"] == body["transaction_id"]

    def test_reject_prevents_confirmation(self, client, auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-3", "body": LOW_CONFIDENCE_SMS},
        ).json()["id"]

        rejected = client.post(f"/api/sms/messages/{message_id}/reject", headers=auth)
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "REJECTED"
        assert rejected.json()["rejection_reason"] == "Rejected by owner"

        # Reject is idempotent.
        assert client.post(
            f"/api/sms/messages/{message_id}/reject", headers=auth
        ).status_code == 200

        # You cannot confirm a message you rejected.
        confirm = client.post(f"/api/sms/messages/{message_id}/confirm", headers=auth)
        assert confirm.status_code == 422


class TestIdempotencyAndDedup:
    def test_replaying_the_same_client_msg_id_returns_the_same_row(self, client, auth):
        first = client.post("/api/sms/messages", headers=auth, json=VALID)
        second = client.post("/api/sms/messages", headers=auth, json=VALID)
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["status"] == "SAVED"

        # Only one transaction was written despite two "received" messages.
        listing = client.get("/api/transactions", headers=auth).json()
        assert listing["total"] == 1

    def test_identical_body_for_two_users_is_two_rows(self, client, auth, other_auth):
        # Deduplication is per-user; one user's message must never collapse
        # another's into the same row.
        alice = client.post("/api/sms/messages", headers=auth, json=VALID).json()
        bob = client.post(
            "/api/sms/messages",
            headers=other_auth,
            json={"client_msg_id": "bob-same-body", "body": DEBIT_SMS},
        ).json()
        assert bob["id"] != alice["id"]
        assert bob["user_id"] != alice["user_id"]

    def test_identical_body_from_another_id_is_deduplicated(self, client, auth):
        first = client.post("/api/sms/messages", headers=auth, json=VALID)
        second = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "msg-1b", "body": DEBIT_SMS},
        )
        assert second.json()["id"] == first.json()["id"]
        assert client.get("/api/transactions", headers=auth).json()["total"] == 1

    def test_error_rows_are_retried_with_the_same_key(self, client, auth, monkeypatch):
        original = sms_parser_module.parse_sms
        calls = {"n": 0}

        def flaky_parser(raw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient failure")
            return original(raw)

        monkeypatch.setattr(sms_parser_module, "parse_sms", flaky_parser)

        failed = client.post("/api/sms/messages", headers=auth, json=VALID)
        assert failed.status_code == 201
        assert failed.json()["status"] == "ERROR"

        monkeypatch.setattr(sms_parser_module, "parse_sms", original)

        retried = client.post("/api/sms/messages", headers=auth, json=VALID)
        assert retried.status_code == 201
        assert retried.json()["id"] == failed.json()["id"]
        assert retried.json()["status"] == "SAVED"
        assert client.get("/api/transactions", headers=auth).json()["total"] == 1


class TestStateGuards:
    def test_cannot_confirm_an_invalid_message(self, client, auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "otp-guard", "body": OTP_SMS},
        ).json()["id"]
        response = client.post(f"/api/sms/messages/{message_id}/confirm", headers=auth)
        assert response.status_code == 422

    def test_cannot_reject_an_invalid_message(self, client, auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "otp-guard-2", "body": OTP_SMS},
        ).json()["id"]
        response = client.post(f"/api/sms/messages/{message_id}/reject", headers=auth)
        assert response.status_code == 422

    def test_reject_records_the_supplied_reason(self, client, auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-reason", "body": LOW_CONFIDENCE_SMS},
        ).json()["id"]
        response = client.post(
            f"/api/sms/messages/{message_id}/reject",
            headers=auth,
            json={"reason": "This is my personal number"},
        )
        assert response.status_code == 200
        assert response.json()["rejection_reason"] == "This is my personal number"


class TestRequestValidation:
    def test_body_over_the_maximum_length_is_rejected(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "too-long", "body": "a" * 4001},
        )
        assert response.status_code == 422

    def test_body_at_the_maximum_length_is_accepted(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "max-long", "body": "a" * 4000},
        )
        assert response.status_code == 201

    def test_blank_client_msg_id_is_rejected(self, client, auth):
        response = client.post(
            "/api/sms/messages", headers=auth, json={"client_msg_id": "", "body": DEBIT_SMS}
        )
        assert response.status_code == 422

    def test_unparseable_received_at_is_rejected(self, client, auth):
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "bad-date", "body": DEBIT_SMS, "received_at": "not-a-date"},
        )
        assert response.status_code == 422

    def test_missing_received_at_defaults_to_now(self, client, auth):
        response = client.post("/api/sms/messages", headers=auth, json=VALID)
        assert response.status_code == 201
        assert response.json()["received_at"] is not None


class TestReceivedAtNormalisation:
    def test_timezone_is_normalised_to_naive_utc(self, client, auth):
        local = datetime(2026, 3, 5, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "tz-1", "body": DEBIT_SMS, "received_at": local.isoformat()},
        )
        assert response.status_code == 201
        stored = datetime.fromisoformat(response.json()["received_at"])
        assert stored == local.astimezone(timezone.utc).replace(tzinfo=None)


class TestFraudPipelineOnIngestedSms:
    def test_large_ingested_debit_is_flagged(self, client, auth, db):
        large_sms = (
            "Your A/c XX1234 is debited by Rs.60,000.00 on 05-Mar-2026 "
            "for SWIGGY via UPI Ref 555555555555. Avl Bal: Rs 1,00,000.00"
        )
        response = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "fraud-1", "body": large_sms},
        )
        assert response.status_code == 201
        transaction = response.json()["transaction"]
        assert transaction["is_flagged"] is True
        # Rule engine alone scores 40 (high amount) + 25 (midnight) = 65; the
        # ML model blends it anywhere at-or-above the flag threshold.
        assert int(transaction["fraud_score"]) >= 30

        alerts = client.get("/api/fraud/alerts", headers=auth).json()["items"]
        mine = [a for a in alerts if a["transaction_id"] == transaction["id"]]
        assert len(mine) == 1
        assert mine[0]["risk_score"] == transaction["fraud_score"]
        assert mine[0]["risk_level"] in ("MEDIUM", "HIGH")


class TestSmsMessagingIsolation:
    def test_messages_are_per_user(self, client, auth, other_auth):
        mine = client.post("/api/sms/messages", headers=auth, json=VALID).json()
        theirs = client.post(
            "/api/sms/messages",
            headers=other_auth,
            json={"client_msg_id": "bob-1", "body": CREDIT_SMS},
        ).json()

        alice_list = client.get("/api/sms/messages", headers=auth).json()
        assert {m["id"] for m in alice_list["items"]} == {mine["id"]}
        assert theirs["id"] not in {m["id"] for m in alice_list["items"]}

    def test_cannot_confirm_another_users_message(self, client, auth, other_auth):
        message_id = client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-iso-1", "body": LOW_CONFIDENCE_SMS},
        ).json()["id"]

        assert client.post(
            f"/api/sms/messages/{message_id}/confirm", headers=other_auth
        ).status_code == 404
        assert client.post(
            f"/api/sms/messages/{message_id}/reject", headers=other_auth
        ).status_code == 404


class TestListEndpoint:
    def test_filters_by_status(self, client, auth):
        client.post("/api/sms/messages", headers=auth, json=VALID)
        client.post(
            "/api/sms/messages",
            headers=auth,
            json={"client_msg_id": "low-1", "body": LOW_CONFIDENCE_SMS},
        )

        saved = client.get("/api/sms/messages?status=SAVED", headers=auth).json()
        assert saved["total"] == 1
        assert saved["items"][0]["status"] == "SAVED"

        pending = client.get("/api/sms/messages", headers=auth).json()["items"]
        statuses = {m["status"] for m in pending}
        assert "SAVED" in statuses
        assert "PENDING_REVIEW" in statuses


class TestAnonymousAccess:
    def test_sms_receive_requires_auth(self, client):
        assert client.post("/api/sms/messages", json=VALID).status_code == 401