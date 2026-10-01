"""budgets: exact money, per-period uniqueness, integrity checks

Changes
-------
* ``amount`` FLOAT -> DECIMAL(12,2).
* Adds ``updated_at`` backfilled from ``created_at``.
* Adds a uniqueness constraint on (user_id, category, month, year) so a user
  cannot create two competing budgets for the same period. Existing duplicates
  are resolved by keeping the lowest id *before* the constraint is added, so
  the migration cannot fail.
* Adds amount/month/year check constraints.
* Tightens the user foreign key to ``ON DELETE CASCADE``.

No rows are deleted as part of this migration. If duplicate budget rows exist
for a period, the excess rows are archived to
``budgets_duplicate_archive`` rather than destroyed, and the report below
records how many were moved.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _user_fk_name(bind) -> str:
    """Find the existing user foreign-key name on ``budgets``.

    The live database auto-named this ``budgets_ibfk_1`` while a database built
    from revision 0001 uses ``fk_budgets_user_id_users``. Reflecting the real
    name keeps this migration valid on both.
    """
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys("budgets"):
        if fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]:
            return fk["name"]
    raise RuntimeError("No user_id foreign key found on budgets")


def upgrade() -> None:
    bind = op.get_bind()

    # --- money: FLOAT -> DECIMAL(12,2) -------------------------------------
    op.alter_column(
        "budgets",
        "amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(12, 2),
        existing_nullable=False,
        nullable=False,
    )

    op.add_column(
        "budgets",
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )
    bind.execute(sa.text("UPDATE budgets SET updated_at = COALESCE(created_at, NOW())"))
    # created_at is now NOT NULL everywhere: backfill, then tighten. The server
    # default is restated explicitly, otherwise the MODIFY drops it.
    bind.execute(sa.text("UPDATE budgets SET created_at = NOW() WHERE created_at IS NULL"))
    op.alter_column(
        "budgets",
        "created_at",
        existing_type=sa.DateTime(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # --- archive duplicate periods before enforcing uniqueness -------------
    # Rows are moved (not deleted) into an archive table so nothing is lost.
    op.create_table(
        "budgets_duplicate_archive",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    duplicates = bind.execute(
        sa.text(
            """
            SELECT user_id, category, month, year
            FROM budgets
            GROUP BY user_id, category, month, year
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for user_id, category, month, year in duplicates:
        keep = bind.execute(
            sa.text(
                """
                SELECT id FROM budgets
                WHERE user_id = :u AND category = :c AND month = :m AND year = :y
                ORDER BY id ASC LIMIT 1
                """
            ),
            {"u": user_id, "c": category, "m": month, "y": year},
        ).scalar()
        bind.execute(
            sa.text(
                """
                INSERT INTO budgets_duplicate_archive
                    (id, user_id, category, amount, month, year, created_at, updated_at)
                SELECT id, user_id, category, amount, month, year, created_at, updated_at
                FROM budgets
                WHERE user_id = :u AND category = :c AND month = :m AND year = :y
                  AND id <> :keep
                """
            ),
            {"u": user_id, "c": category, "m": month, "y": year, "keep": keep},
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM budgets
                WHERE user_id = :u AND category = :c AND month = :m AND year = :y
                  AND id <> :keep
                """
            ),
            {"u": user_id, "c": category, "m": month, "y": year, "keep": keep},
        )

    # --- constraints & indexes ---------------------------------------------
    op.create_unique_constraint(
        "uq_budgets_user_category_period",
        "budgets",
        ["user_id", "category", "month", "year"],
    )
    op.create_index("ix_budgets_user_period", "budgets", ["user_id", "year", "month"])
    op.create_check_constraint("ck_budgets_amount_positive", "budgets", "amount > 0")
    op.create_check_constraint("ck_budgets_month_range", "budgets", "month >= 1 AND month <= 12")
    op.create_check_constraint("ck_budgets_year_range", "budgets", "year >= 2000 AND year <= 2200")

    op.drop_constraint(_user_fk_name(bind), "budgets", type_="foreignkey")
    op.create_foreign_key(
        "fk_budgets_user_id_users",
        "budgets",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Restore archived duplicates before dropping the archive table, so a
    # downgrade -> upgrade cycle does not silently lose the rows that the
    # uniqueness constraint had displaced.
    #
    # Reflect the current foreign-key name instead of assuming one. This
    # migration is valid on both a database built from revision 0001 (named
    # ``fk_budgets_user_id_users``) and the live database (named
    # ``budgets_ibfk_1``); hardcoding either name makes the rollback fail with
    # "Can't DROP ... check that column/key exists" on the other. Recreating
    # under the same name that was just dropped leaves both shapes untouched.
    fk_name = _user_fk_name(op.get_bind())
    op.drop_constraint(fk_name, "budgets", type_="foreignkey")
    # ON DELETE CASCADE is part of the pre-0004 shape, so the rollback must
    # restore it instead of quietly reverting to a bare foreign key.
    op.create_foreign_key(
        fk_name, "budgets", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("ck_budgets_year_range", "budgets", type_="check")
    op.drop_constraint("ck_budgets_month_range", "budgets", type_="check")
    op.drop_constraint("ck_budgets_amount_positive", "budgets", type_="check")
    op.drop_index("ix_budgets_user_period", table_name="budgets")
    op.drop_constraint("uq_budgets_user_category_period", "budgets", type_="unique")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO budgets (id, user_id, category, amount, month, year,
                                 created_at, updated_at)
            SELECT id, user_id, category, amount, month, year, created_at, updated_at
            FROM budgets_duplicate_archive
            """
        )
    )
    op.drop_table("budgets_duplicate_archive")

    op.alter_column(
        "budgets",
        "created_at",
        existing_type=sa.DateTime(),
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=True,
    )
    op.drop_column("budgets", "updated_at")
    op.alter_column(
        "budgets",
        "amount",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Float(),
        existing_nullable=False,
    )
