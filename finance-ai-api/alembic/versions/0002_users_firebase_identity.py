"""users: Firebase identity fields, nullable password, updated_at

Changes
-------
* ``password`` renamed to ``password_hash`` and made NULLABLE. Firebase
  Authentication users never have a local password. The rename uses
  ``CHANGE COLUMN`` so every existing hash is preserved in place.
* Adds ``firebase_uid`` (unique), ``email_verified``, ``phone_number`` and
  ``last_login_at``.
* Adds ``updated_at`` backfilled from ``created_at`` so existing rows satisfy
  the NOT NULL constraint.
* ``role`` enum defaults to MEMBER for every existing row.

No rows are deleted and no existing value is overwritten.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- rename + relax the password column -------------------------------
    op.alter_column(
        "users",
        "password",
        new_column_name="password_hash",
        existing_type=sa.String(length=255),
        existing_nullable=False,
        nullable=True,
    )

    # --- Firebase identity -------------------------------------------------
    op.add_column("users", sa.Column("firebase_uid", sa.String(length=128), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("users", sa.Column("phone_number", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
    )

    # --- updated_at, backfilled so NOT NULL holds for existing rows --------
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    bind.execute(sa.text("UPDATE users SET updated_at = COALESCE(created_at, NOW())"))
    bind.execute(sa.text("UPDATE users SET role = 'MEMBER' WHERE role IS NULL"))
    bind.execute(sa.text("UPDATE users SET email_verified = 0 WHERE email_verified IS NULL"))

    # created_at is now NOT NULL everywhere: backfill, then tighten. The server
    # default is restated explicitly, otherwise the MODIFY drops it.
    bind.execute(sa.text("UPDATE users SET created_at = NOW() WHERE created_at IS NULL"))
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # --- indexes -----------------------------------------------------------
    op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)

    # --- role enum ---------------------------------------------------------
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=20),
        type_=sa.Enum("OWNER", "MEMBER", name="userrole"),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("'MEMBER'"),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.Enum("OWNER", "MEMBER", name="userrole"),
        type_=sa.String(length=20),
        existing_nullable=False,
        nullable=True,
        server_default=None,
    )
    op.drop_index("ix_users_firebase_uid", table_name="users")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "firebase_uid")
    op.alter_column(
        "users",
        "password_hash",
        new_column_name="password",
        existing_type=sa.String(length=255),
        existing_nullable=True,
        nullable=False,
    )
