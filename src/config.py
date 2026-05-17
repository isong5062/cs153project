"""Typed application settings loaded from environment / .env."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Env(str, Enum):
    DEV = "dev"
    PROD = "prod"


ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_URL = "https://api.alpaca.markets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ──
    env: Env = Env.DEV
    log_level: str = "INFO"

    # ── Broker ──
    broker_mode: BrokerMode = BrokerMode.PAPER
    alpaca_api_key: SecretStr = SecretStr("")
    alpaca_api_secret: SecretStr = SecretStr("")
    alpaca_base_url: str | None = None  # resolved from broker_mode if unset

    # ── LLM ──
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model_default: str = "claude-sonnet-4-5"
    anthropic_model_reflection: str = "claude-opus-4-5"
    max_agent_tokens_per_day: int = 2_000_000

    # ── Risk ──
    risk_per_trade_pct: float = Field(0.01, gt=0, lt=1)
    max_position_pct: float = Field(0.05, gt=0, lt=1)
    max_concurrent_positions: int = Field(10, gt=0)
    daily_loss_limit_pct: float = Field(0.02, gt=0, lt=1)
    max_drawdown_pct: float = Field(0.08, gt=0, lt=1)

    # ── Persistence ──
    postgres_url: str = "postgresql+psycopg://bot:bot@localhost:5432/bot"
    redis_url: str = "redis://localhost:6379/0"

    @model_validator(mode="after")
    def _resolve_alpaca_base_url(self) -> Settings:
        if self.alpaca_base_url is None:
            self.alpaca_base_url = (
                ALPACA_LIVE_URL if self.broker_mode == BrokerMode.LIVE else ALPACA_PAPER_URL
            )
        return self

    @property
    def is_paper(self) -> bool:
        return self.broker_mode == BrokerMode.PAPER


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Tests can clear the cache via `get_settings.cache_clear()`."""
    return Settings()
