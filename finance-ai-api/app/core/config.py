"""Application configuration loaded from environment variables.

All configuration is read once at import time from the process environment.
``.env`` is loaded from the backend project root so that the backend starts
correctly regardless of the current working directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    if raw.strip().startswith("["):
        try:
            return [str(x).strip() for x in json.loads(raw)]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def _path(name: str, default: Optional[Path] = None) -> Optional[Path]:
    raw = os.getenv(name)
    if raw and raw.strip():
        candidate = Path(raw.strip())
        if not candidate.is_absolute():
            candidate = BACKEND_ROOT / candidate
        return candidate
    return default


@dataclass(frozen=True)
class Settings:
    app_name: str = "Finance-AI API"
    app_version: str = "2.0.0"
    app_env: str = "development"
    debug: bool = False

    # --- Core security -----------------------------------------------------
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = field(
        default_factory=lambda: _int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
    )
    # Development-only token provider. Automatically ignored whenever Firebase
    # credentials are present, so production can never fall back to it.
    allow_dev_auth: bool = field(
        default_factory=lambda: _bool("ALLOW_DEV_AUTH", False)
    )

    cors_origins: List[str] = field(
        default_factory=lambda: _list(
            "CORS_ORIGINS",
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
            ],
        )
    )
    cors_allow_credentials: bool = field(
        default_factory=lambda: _bool("CORS_ALLOW_CREDENTIALS", False)
    )

    # --- Database ----------------------------------------------------------
    db_user: str = field(default_factory=lambda: os.getenv("DB_USER", ""))
    db_password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))
    db_host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    db_port: str = field(default_factory=lambda: os.getenv("DB_PORT", "3306"))
    db_name: str = field(default_factory=lambda: os.getenv("DB_NAME", "finance_ai"))
    db_echo: bool = field(default_factory=lambda: _bool("DB_ECHO", False))

    # --- Firebase Authentication -------------------------------------------
    firebase_project_id: str = field(
        default_factory=lambda: os.getenv("FIREBASE_PROJECT_ID", "")
    )
    firebase_credentials_path: Optional[Path] = field(
        default_factory=lambda: _path("FIREBASE_CREDENTIALS_PATH")
    )
    firebase_credentials_json: str = field(
        default_factory=lambda: os.getenv("FIREBASE_CREDENTIALS_JSON", "")
    )

    # --- Google Cloud Storage ---------------------------------------------
    gcs_bucket: str = field(default_factory=lambda: os.getenv("GCS_BUCKET", ""))
    google_application_credentials: Optional[Path] = field(
        default_factory=lambda: _path("GOOGLE_APPLICATION_CREDENTIALS")
    )

    # --- Google Drive ------------------------------------------------------
    google_drive_folder_id: str = field(
        default_factory=lambda: os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    )
    google_drive_credentials_path: Optional[Path] = field(
        default_factory=lambda: _path("GOOGLE_DRIVE_CREDENTIALS_PATH")
    )

    # --- Financial Assistant ----------------------------------------------
    assistant_provider: str = field(
        default_factory=lambda: os.getenv("ASSISTANT_PROVIDER", "builtin")
    )
    assistant_api_key: str = field(
        default_factory=lambda: os.getenv("ASSISTANT_API_KEY", "")
    )
    assistant_model: str = field(
        default_factory=lambda: os.getenv("ASSISTANT_MODEL", "gpt-4o-mini")
    )
    assistant_base_url: str = field(
        default_factory=lambda: os.getenv("ASSISTANT_BASE_URL", "")
    )

    # --- Behaviour ---------------------------------------------------------
    recent_transaction_limit: int = field(
        default_factory=lambda: _int("RECENT_TRANSACTION_LIMIT", 10)
    )

    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def firebase_enabled(self) -> bool:
        """True when enough configuration exists to verify Firebase ID tokens."""
        if not self.firebase_project_id:
            return False
        if self.firebase_credentials_path or self.firebase_credentials_json:
            return True
        # Application Default Credentials may also be available.
        return os.getenv("GOOGLE_APPLICATION_CREDENTIALS") is not None

    @property
    def dev_auth_active(self) -> bool:
        """Dev token provider is only usable when explicitly enabled AND when
        Firebase is NOT configured. This guarantees a single auth architecture
        in production."""
        return self.allow_dev_auth and not self.firebase_enabled and bool(self.secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()