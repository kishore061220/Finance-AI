"""Alembic environment.

The database URL is built from the same environment configuration the
application uses, so credentials never live inside the repository.

Important safety behaviour
--------------------------
``compare_type`` and ``compare_server_default`` are enabled so autogenerate
detects the ``FLOAT -> DECIMAL`` money change and server-default drift.

The ``sqlalchemy.url`` in ``alembic.ini`` is intentionally empty; it is filled
in at runtime below.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the backend root is importable so ``app.*`` resolves.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database.connection import DATABASE_URL, Base  # noqa: E402
import app.models  # noqa: F401,E402  (imports every model -> registers metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ``configparser`` treats ``%`` as its interpolation marker, and the URL-encoded
# database password legitimately contains ``%xx`` sequences. Escaping them as
# ``%%`` keeps the literal value intact through interpolation.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to the database."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # Do not generate a DROP for an index that only differs by name.
            compare_indexes=True,
            render_as_batch=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
