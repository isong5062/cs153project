"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from src.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> Iterator[None]:
    """Clear the settings LRU cache so env-var overrides in tests take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal env for tests that construct Settings without a real .env."""
    for key in (
        "BROKER_MODE",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "ANTHROPIC_API_KEY",
        "POSTGRES_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BROKER_MODE", "paper")
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_API_SECRET", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+psycopg://bot:bot@localhost:5432/bot_test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    # Ensure no .env file is read for these tests
    os.environ.pop("ENV_FILE", None)
