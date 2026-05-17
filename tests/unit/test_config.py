"""Sanity tests for src.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import ALPACA_LIVE_URL, ALPACA_PAPER_URL, BrokerMode, Settings


def test_defaults_to_paper(fake_env: None) -> None:
    s = Settings()
    assert s.broker_mode == BrokerMode.PAPER
    assert s.is_paper is True
    assert s.alpaca_base_url == ALPACA_PAPER_URL


def test_live_mode_resolves_live_url(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BROKER_MODE", "live")
    s = Settings()
    assert s.broker_mode == BrokerMode.LIVE
    assert s.is_paper is False
    assert s.alpaca_base_url == ALPACA_LIVE_URL


def test_risk_bounds_are_enforced(fake_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISK_PER_TRADE_PCT", "1.5")  # invalid: >= 1
    with pytest.raises(ValidationError):
        Settings()


def test_explicit_alpaca_base_url_overrides(
    fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", "https://example.test")
    s = Settings()
    assert s.alpaca_base_url == "https://example.test"
