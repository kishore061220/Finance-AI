"""sms_messages ingest ledger

Additive - creates one new table (sms_messages). No existing table is altered,
so this revision is safe to apply to the live database.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision = "0006"
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
    op.create_table(
        "sms_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_msg_id", sa.String(length=64), nullable=False),
        sa.Column("sender", sa.String(length=32), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "SAVED",
                "DUPLICATE",
                "PENDING_REVIEW",
                "INVALID",
                "REJECTED",
                "ERROR",
                name="smsingeststatus",
            ),
            nullable=False,
        ),
        sa.Column("parsed", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        TS,
        TU,
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "client_msg_id", name="uq_sms_messages_user_client"
        ),
        sa.UniqueConstraint("user_id", "body_hash", name="uq_sms_messages_user_body_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sms_messages_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_sms_messages_transaction_id_transactions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_sms_messages_id", "sms_messages", ["id"])
    op.create_index("ix_sms_messages_user_id", "sms_messages", ["user_id"])
    op.create_index("ix_sms_messages_transaction_id", "sms_messages", ["transaction_id"])
    op.create_index(
        "ix_sms_messages_user_status", "sms_messages", ["user_id", "status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("sms_messages")