"""backup provider LOCAL, and pending family invitations

Two small follow-up changes to the tables created by revision 0005. They live in
their own revision because 0005 has already been applied to some databases, and
an applied migration must never be edited in place: doing so leaves those
databases permanently out of sync with the models, which ``alembic check``
reports as a pending operation that no existing revision will ever perform.

1. ``backup_records.provider`` gains a ``LOCAL`` value, so a backup can be
   written to the server's own filesystem when no cloud provider is configured
   (and so verification works without credentials).
2. ``family_members.user_id`` becomes nullable, because an invitation can be
   addressed to an email address that has never registered. Until the recipient
   signs in there is no user row to point at; ``invited_email`` and
   ``invited_user_id`` carry the pending invitation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

CLOUD_PROVIDERS = ("FIREBASE_STORAGE", "GOOGLE_CLOUD_STORAGE", "GOOGLE_DRIVE")
ALL_PROVIDERS = ("LOCAL",) + CLOUD_PROVIDERS


def upgrade() -> None:
    # --- backups: allow the on-disk provider -------------------------------
    op.alter_column(
        "backup_records",
        "provider",
        existing_type=sa.Enum(*CLOUD_PROVIDERS, name="backupprovider"),
        type_=sa.Enum(*ALL_PROVIDERS, name="backupprovider"),
        existing_nullable=False,
    )

    # --- family: an invite can precede the recipient's first sign-in -------
    op.alter_column(
        "family_members",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Removing an ENUM value fails outright if any row still uses it, and
    # silently coercing those rows to '' would destroy the record of which
    # provider was used. Refuse instead, and say what to do about it.
    bind = op.get_bind()
    used = bind.execute(
        sa.text("SELECT COUNT(*) FROM backup_records WHERE provider = 'LOCAL'")
    ).scalar()
    if used:
        raise RuntimeError(
            f"Cannot downgrade: {used} backup record(s) reference the LOCAL "
            "provider, which revision 0006 introduced. Delete or reassign those "
            "rows to a cloud provider before downgrading."
        )

    op.alter_column(
        "backup_records",
        "provider",
        existing_type=sa.Enum(*ALL_PROVIDERS, name="backupprovider"),
        type_=sa.Enum(*CLOUD_PROVIDERS, name="backupprovider"),
        existing_nullable=False,
    )

    # user_id cannot go back to NOT NULL while pending invitations exist.
    pending = bind.execute(
        sa.text("SELECT COUNT(*) FROM family_members WHERE user_id IS NULL")
    ).scalar()
    if pending:
        raise RuntimeError(
            f"Cannot downgrade: {pending} family member row(s) have no user_id "
            "because the invitation has not been accepted. Remove those pending "
            "invitations before downgrading."
        )

    op.alter_column(
        "family_members",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
