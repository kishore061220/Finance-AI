"""The application must import and its test suite must run with no database
credentials configured.

This is a regression guard, not a style preference. The engine used to be built
at import time, so any process that imported the app without a ``.env`` present
died with ``RuntimeError: DB_USER is not configured in the environment``. On a
developer machine the ``.env`` hides this; on a CI runner there is no ``.env``,
so the entire API job failed at collection time.

The tests below deliberately do NOT inject fake ``DB_USER``/``DB_PASSWORD``
values into the environment. Doing that would let a test reach the configured
MySQL database - which is the real live one on a developer machine - and it would
mask the very import-time coupling this file exists to catch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_without_db_env(code: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a fresh interpreter with no database credentials.

    A subprocess is required: the engine and settings are cached at import time
    inside the pytest process, and ``.env`` is loaded on import of
    ``app.core.config``, so clearing ``os.environ`` here would not reproduce what
    a CI runner sees.
    """
    env = {
        key: value
        for key, value in __import__("os").environ.items()
        if key not in {"DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"}
    }
    # An empty value is treated as "not configured" by app.core.config, and it
    # also stops python-dotenv from re-populating the variables from a local
    # .env file, which would otherwise defeat the point of the test.
    env.update(
        {
            "DB_USER": "",
            "DB_PASSWORD": "",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


class TestNoDatabaseCredentialsRequiredAtImport:
    def test_importing_the_app_needs_no_db_user(self):
        result = _run_without_db_env("import main")
        assert result.returncode == 0, result.stderr

    def test_importing_main_module_needs_no_db_credentials(self):
        result = _run_without_db_env("import main")
        assert result.returncode == 0, result.stderr

    def test_importing_the_models_needs_no_db_credentials(self):
        result = _run_without_db_env("import app.models")
        assert result.returncode == 0, result.stderr

    def test_the_engine_is_not_built_on_import(self):
        """Importing must not open a connection either."""
        result = _run_without_db_env(
            "import app.database.connection as c; "
            "assert c._engine is None, 'engine was built at import time'"
        )
        assert result.returncode == 0, result.stderr

    def test_building_the_url_still_fails_loudly_without_credentials(self):
        """The lazy path must not have turned a missing credential into a
        connection attempt against some default server."""
        result = _run_without_db_env(
            "import app.database.connection as c\n"
            "try:\n"
            "    c.get_database_url()\n"
            "except RuntimeError as exc:\n"
            "    assert 'DB_USER' in str(exc), exc\n"
            "else:\n"
            "    raise AssertionError('expected RuntimeError')\n"
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "module",
        ["app.core.config", "app.core.security", "app.database.connection"],
    )
    def test_core_modules_import_without_credentials(self, module):
        result = _run_without_db_env(f"import {module}")
        assert result.returncode == 0, result.stderr
