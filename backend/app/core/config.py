"""Application settings (env-driven, cached)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (two parents up from app/core/config.py)
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "regime_trader.sqlite3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    database_url: str = Field(default="")
    cors_origins: str = "http://localhost:3000"

    # Alpaca — PAPER ONLY in v1 (enforced by the paper-lock guard in later phases)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    # Anthropic (self-learning #4)
    anthropic_api_key: str = ""

    # Operational alerts (optional webhook; empty disables the webhook channel)
    alert_webhook_url: str = ""

    @property
    def resolved_database_url(self) -> str:
        """Use DATABASE_URL if set, else a local SQLite file (zero-config dev)."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
