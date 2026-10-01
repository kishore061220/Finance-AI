"""transactions: exact money, source tracking, fraud fields, constraints

Changes
-------
* ``amount`` FLOAT -> DECIMAL(12,2). Money must not be binary floating point.
  The cast rounds to 2 decimals, which is the correct precision for currency.
* ``transaction_type`` VARCHAR(20) -> ENUM('income','expense').
* ``description`` VARCHAR(255) -> TEXT so long notes are not truncated.
* Adds ``source``, ``bank_reference``, ``raw_source_text``,
  ``categorization_source``, ``fraud_score`` and ``is_flagged``.
* Adds ``updated_at`` backfilled from ``created_at``.
* Adds amount/category/indexes for the dashboard query patterns.
* Tightens the user foreign key to ``ON DELETE CASCADE`` so deleting a user
  cannot leave orphaned financial rows (previously NO ACTION).

No rows are deleted.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _user_fk_name(bind) -> str:
    """Find the existing user foreign-key name on ``transactions``.

    The live database auto-named this ``transactions_ibfk_1`` while a database
    built from revision 0001 uses ``fk_transactions_user_id_users``. Reflecting
    the real name keeps this migration valid on both.
    """
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys("transactions"):
        if fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]:
            return fk["name"]
    raise RuntimeError("No user_id foreign key found on transactions")


def upgrade() -> None:
    bind = op.get_bind()

    # --- money: FLOAT -> DECIMAL(12,2) -------------------------------------
    op.alter_column(
        "transactions",
        "amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        nullable=False,
    )

    # --- transaction_type -> enum -----------------------------------------
    op.alter_column(
        "transactions",
        "transaction_type",
        existing_type=sa.String(length=20),
        type_=sa.Enum("income", "expense", name="transactiontype"),
        existing_nullable=False,
    )

    # --- description -> TEXT ----------------------------------------------
    op.alter_column(
        "transactions",
        "description",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )

    # --- new columns -------------------------------------------------------
    op.add_column(
        "transactions",
        sa.Column(
            "source",
            sa.Enum("MANUAL", "SMS", "OCR", "IMPORT", name="transactionsource"),
            server_default=sa.text("'MANUAL'"),
            nullable=False,
        ),
    )
    op.add_column(
        "transactions", sa.Column("bank_reference", sa.String(length=120), nullable=True)
    )
    op.add_column("transactions", sa.Column("raw_source_text", sa.Text(), nullable=True))
    op.add_column(
        "transactions", sa.Column("categorization_source", sa.String(length=32), nullable=True)
    )
    op.add_column("transactions", sa.Column("fraud_score", sa.Integer(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("is_flagged", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )
    bind.execute(
        sa.text("UPDATE transactions SET updated_at = COALESCE(created_at, NOW())")
    )
    # created_at is now NOT NULL everywhere: backfill, then tighten. The server
    # default is restated explicitly, otherwise the MODIFY drops it.
    bind.execute(
        sa.text("UPDATE transactions SET created_at = NOW() WHERE created_at IS NULL")
    )
    op.alter_column(
        "transactions",
        "created_at",
        existing_type=sa.DateTime(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # --- indexes for the dashboard / filter query patterns -----------------
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index("ix_transactions_bank_reference", "transactions", ["bank_reference"])
    op.create_index("ix_transactions_transaction_date", "transactions", ["transaction_date"])
    op.create_index(
        "ix_transactions_user_date", "transactions", ["user_id", "transaction_date"]
    )
    op.create_index(
        "ix_transactions_user_type_date",
        "transactions",
        ["user_id", "transaction_type", "transaction_date"],
    )

    # --- integrity checks ---------------------------------------------------
    op.create_check_constraint("ck_transactions_amount_positive", "transactions", "amount > 0")
    op.create_check_constraint(
        "ck_transactions_type_valid",
        "transactions",
        "transaction_type IN ('income','expense')",
    )

    # --- user FK -> CASCADE -------------------------------------------------
    op.drop_constraint(_user_fk_name(bind), "transactions", type_="foreignkey")
    op.create_foreign_key(
        "fk_transactions_user_id_users",
        "transactions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Reflect the current foreign-key name rather than assuming one: this
    # migration runs against both a database built from revision 0001 (named
    # ``fk_transactions_user_id_users``) and the live database (named
    # ``transactions_ibfk_1``). Hardcoding either name makes the rollback fail
    # with "Can't DROP ... check that column/key exists" on the other, which
    # would block any attempt to recover from a bad upgrade. Recreating under
    # the name that was just dropped leaves both shapes untouched.
    fk_name = _user_fk_name(op.get_bind())
    op.drop_constraint(fk_name, "transactions", type_="foreignkey")
    # ON DELETE CASCADE is part of the pre-0003 shape (it is what keeps user
    # deletion from leaving orphaned transactions), so the rollback must restore
    # it rather than quietly reverting to a bare foreign key.
    op.create_foreign_key(
        fk_name, "transactions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("ck_transactions_type_valid", "transactions", type_="check")
    op.drop_constraint("ck_transactions_amount_positive", "transactions", type_="check")

    op.drop_index("ix_transactions_user_type_date", table_name="transactions")
    op.drop_index("ix_transactions_user_date", table_name="transactions")
    op.drop_index("ix_transactions_transaction_date", table_name="transactions")
    op.drop_index("ix_transactions_bank_reference", table_name="transactions")
    op.drop_index("ix_transactions_category", table_name="transactions")

    op.drop_column("transactions", "updated_at")
    op.drop_column("transactions", "is_flagged")
    op.drop_column("transactions", "fraud_score")
    op.drop_column("transactions", "categorization_source")
    op.drop_column("transactions", "raw_source_text")
    op.drop_column("transactions", "bank_reference")
    op.drop_column("transactions", "source")

    op.alter_column(
        "transactions",
        "description",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "transactions",
        "transaction_type",
        existing_type=sa.Enum("income", "expense", name="transactiontype"),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "transactions",
        "amount",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Float(),
        existing_nullable=False,
    )
