"""new feature tables: fraud alerts, family, loans, notifications, backups, reports

Purely additive - creates 11 new tables. No existing table is altered, so this
revision is safe to apply to the live database.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False)
TU = sa.Column(
    "updated_at",
    sa.DateTime(),
    server_default=sa.text("CURRENT_TIMESTAMP"),
    nullable=False,
)


def upgrade() -> None:
    # ------------------------------------------------------------------ fraud
    op.create_table(
        "fraud_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum("LOW", "MEDIUM", "HIGH", name="risklevel"),
            nullable=False,
        ),
        sa.Column("is_fraud", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "detection_layer",
            sa.Enum("RULES", "ML", "COMBINED", name="detectionlayer"),
            server_default=sa.text("'RULES'"),
            nullable=False,
        ),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("amount_snapshot", sa.Numeric(12, 2), nullable=True),
        sa.Column("merchant_snapshot", sa.String(length=150), nullable=True),
        sa.Column("category_snapshot", sa.String(length=100), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "is_dismissed", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("notified", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_fraud_alerts_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_fraud_alerts_transaction_id_transactions",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_fraud_alerts_id", "fraud_alerts", ["id"])
    op.create_index("ix_fraud_alerts_user_id", "fraud_alerts", ["user_id"])
    op.create_index("ix_fraud_alerts_transaction_id", "fraud_alerts", ["transaction_id"])
    op.create_index(
        "ix_fraud_alerts_user_created", "fraud_alerts", ["user_id", "created_at"]
    )
    op.create_index("ix_fraud_alerts_user_read", "fraud_alerts", ["user_id", "is_read"])

    # ----------------------------------------------------------------- family
    op.create_table(
        "family_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_family_groups_owner_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_family_groups_id", "family_groups", ["id"])
    op.create_index("ix_family_groups_owner_id", "family_groups", ["owner_id"])

    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("invited_user_id", sa.Integer(), nullable=True),
        sa.Column("invited_email", sa.String(length=150), nullable=True),
        sa.Column(
            "role",
            sa.Enum("OWNER", "MEMBER", name="familyrole"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "ACTIVE", "REMOVED", name="memberstatus"),
            nullable=False,
        ),
        sa.Column(
            "can_view_all", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "family_id", "user_id", name="uq_family_members_family_user"
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["family_groups.id"],
            name="fk_family_members_family_id_family_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_family_members_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invited_user_id"],
            ["users.id"],
            name="fk_family_members_invited_user_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_family_members_id", "family_members", ["id"])
    op.create_index("ix_family_members_family_id", "family_members", ["family_id"])
    op.create_index("ix_family_members_user_id", "family_members", ["user_id"])
    op.create_index("ix_family_members_invited_user_id", "family_members", ["invited_user_id"])
    op.create_index("ix_family_members_user", "family_members", ["user_id"])

    op.create_table(
        "shared_expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("expense_date", sa.DateTime(), nullable=False),
        sa.Column(
            "is_settled", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["family_groups.id"],
            name="fk_shared_expenses_family_id_family_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_shared_expenses_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_shared_expenses_transaction_id_transactions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_shared_expenses_id", "shared_expenses", ["id"])
    op.create_index("ix_shared_expenses_family_id", "shared_expenses", ["family_id"])
    op.create_index("ix_shared_expenses_transaction_id", "shared_expenses", ["transaction_id"])
    op.create_index(
        "ix_shared_expenses_family_date", "shared_expenses", ["family_id", "expense_date"]
    )

    op.create_table(
        "expense_splits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shared_expense_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("owed_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "settled_amount",
            sa.Numeric(12, 2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "is_settled", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shared_expense_id", "user_id", name="uq_expense_splits_user"
        ),
        sa.ForeignKeyConstraint(
            ["shared_expense_id"],
            ["shared_expenses.id"],
            name="fk_expense_splits_shared_expense_id_shared_expenses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_expense_splits_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_expense_splits_id", "expense_splits", ["id"])
    op.create_index(
        "ix_expense_splits_shared_expense_id", "expense_splits", ["shared_expense_id"]
    )
    op.create_index("ix_expense_splits_user_id", "expense_splits", ["user_id"])

    # ------------------------------------------------------------------ loans
    op.create_table(
        "loans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("lender", sa.String(length=150), nullable=True),
        sa.Column(
            "loan_type",
            sa.Enum(
                "Home Loan",
                "Car Loan",
                "Personal Loan",
                "Education Loan",
                "Business Loan",
                "Other",
                name="loantype",
            ),
            nullable=False,
        ),
        sa.Column("principal", sa.Numeric(14, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("tenure_months", sa.Integer(), nullable=False),
        sa.Column("monthly_emi", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_payable", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "CLOSED", "FORECLOSED", name="loanstatus"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=255), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("principal > 0", name="ck_loans_principal_positive"),
        sa.CheckConstraint("interest_rate >= 0", name="ck_loans_rate_non_negative"),
        sa.CheckConstraint("tenure_months > 0", name="ck_loans_tenure_positive"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_loans_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_loans_id", "loans", ["id"])
    op.create_index("ix_loans_user_id", "loans", ["user_id"])
    op.create_index("ix_loans_user_status", "loans", ["user_id", "status"])

    op.create_table(
        "loan_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("loan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("principal_component", sa.Numeric(12, 2), nullable=True),
        sa.Column("interest_component", sa.Numeric(12, 2), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PAID", "OVERDUE", name="paymentstatus"),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "loan_id", "installment_number", name="uq_loan_payments_installment"
        ),
        sa.ForeignKeyConstraint(
            ["loan_id"], ["loans.id"], name="fk_loan_payments_loan_id_loans", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_loan_payments_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_loan_payments_transaction_id_transactions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_loan_payments_id", "loan_payments", ["id"])
    op.create_index("ix_loan_payments_loan_id", "loan_payments", ["loan_id"])
    op.create_index("ix_loan_payments_user_id", "loan_payments", ["user_id"])
    op.create_index("ix_loan_payments_loan_due", "loan_payments", ["loan_id", "due_date"])

    # ---------------------------------------------------------- notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "notification_type",
            sa.Enum(
                "FRAUD_ALERT",
                "BUDGET_WARNING",
                "LOAN_DUE",
                "FAMILY",
                "SYSTEM",
                "ASSISTANT",
                name="notificationtype",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("body", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("deep_link", sa.String(length=120), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_notifications_id", "notifications", ["id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])

    # ----------------------------------------------------------- device tokens
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("ANDROID", "IOS", "WEB", name="deviceplatform"),
            nullable=False,
        ),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_device_tokens_token"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_device_tokens_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_device_tokens_id", "device_tokens", ["id"])
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_index("ix_device_tokens_user_active", "device_tokens", ["user_id", "is_active"])

    # ---------------------------------------------------------------- backups
    op.create_table(
        "backup_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "FIREBASE_STORAGE",
                "GOOGLE_CLOUD_STORAGE",
                "GOOGLE_DRIVE",
                name="backupprovider",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SUCCESS", "FAILED", name="backupstatus"),
            nullable=False,
        ),
        sa.Column("remote_path", sa.String(length=512), nullable=True),
        sa.Column("remote_url", sa.String(length=512), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_backup_records_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_backup_records_id", "backup_records", ["id"])
    op.create_index("ix_backup_records_user_id", "backup_records", ["user_id"])
    op.create_index(
        "ix_backup_records_user_created", "backup_records", ["user_id", "created_at"]
    )

    # ---------------------------------------------------------------- reports
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "report_type",
            sa.Enum(
                "TRANSACTIONS",
                "INCOME",
                "EXPENSES",
                "CATEGORIES",
                "FRAUD",
                "BUDGETS",
                "SPENDING_TRENDS",
                "LOANS",
                name="reporttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "report_format",
            sa.Enum("CSV", "EXCEL", "PDF", name="reportformat"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_reports_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_reports_id", "reports", ["id"])
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_user_created", "reports", ["user_id", "created_at"])


def downgrade() -> None:
    for table in (
        "reports",
        "backup_records",
        "device_tokens",
        "notifications",
        "loan_payments",
        "loans",
        "expense_splits",
        "shared_expenses",
        "family_members",
        "family_groups",
        "fraud_alerts",
    ):
        op.drop_table(table)
