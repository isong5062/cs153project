"""SignalProducer turns strategy transitions into entry/exit intents."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

import pandas as pd
import pytest

from src.execution.signal_producer import ProducerConfig, SignalProducer
from src.signals.strategies.base import (
    ACTION_FLAT,
    ACTION_LONG,
    BaseStrategy,
)


@dataclass
class _ScriptedStrategy(BaseStrategy):
    """Returns whatever signal sequence the test gives it."""

    name: ClassVar[str] = "scripted"
    version: ClassVar[str] = "v1"
    default_params: ClassVar[dict[str, Any]] = {}

    actions: list[str] = field(default_factory=list)

    def required_history_bars(self) -> int:
        return 2

    def _signals(self, data: pd.DataFrame) -> pd.DataFrame:
        n = len(data)
        actions = self.actions[-n:] if len(self.actions) >= n else (
            [ACTION_FLAT] * (n - len(self.actions)) + self.actions
        )
        return pd.DataFrame(
            {"action": actions, "confidence": [0.5] * n},
            index=data.index,
        )


def _bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=idx,
    )


def _producer(
    *, monkeypatch: pytest.MonkeyPatch, bars: dict[str, pd.DataFrame],
    strategies, stop_pct: float = 0.05,
) -> SignalProducer:
    # Patch load_bars in the producer module so we don't touch Postgres.
    monkeypatch.setattr(
        "src.execution.signal_producer.load_bars",
        lambda symbols, start, end, timeframe: {s: bars[s] for s in symbols if s in bars},
    )
    return SignalProducer(
        ProducerConfig(
            universe=list(bars.keys()),
            strategies=strategies,
            stop_pct=stop_pct,
            lookback_days=10,
        )
    )


def test_emits_entry_on_flat_to_long_transition(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_FLAT, ACTION_LONG])
    producer = _producer(monkeypatch=monkeypatch, bars={"AAPL": _bars([99, 100, 101])}, strategies=[strat])
    intents = producer()
    assert len(intents) == 1
    intent = intents[0]
    assert intent.symbol == "AAPL"
    assert intent.is_entry is True
    assert intent.is_exit is False
    assert intent.entry_price == Decimal("101")
    # 5% stop default
    assert intent.stop_price == Decimal("101") * (Decimal("1") - Decimal("0.05"))


def test_emits_exit_on_long_to_flat_transition(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_LONG, ACTION_FLAT])
    producer = _producer(monkeypatch=monkeypatch, bars={"AAPL": _bars([100, 101, 99])}, strategies=[strat])
    intents = producer()
    assert len(intents) == 1
    assert intents[0].is_exit is True
    assert intents[0].is_entry is False


def test_no_transition_no_intent(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_LONG, ACTION_LONG, ACTION_LONG])
    producer = _producer(monkeypatch=monkeypatch, bars={"AAPL": _bars([100, 101, 102])}, strategies=[strat])
    assert producer() == []


def test_skips_symbols_with_insufficient_history(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_LONG])
    # Only 1 bar; required_history_bars() == 2.
    producer = _producer(monkeypatch=monkeypatch, bars={"AAPL": _bars([100])}, strategies=[strat])
    assert producer() == []


def test_strategy_name_carries_version(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_LONG])
    producer = _producer(monkeypatch=monkeypatch, bars={"AAPL": _bars([100, 101])}, strategies=[strat])
    intents = producer()
    assert intents[0].strategy_name == "scripted@v1"


def test_no_bars_returns_empty(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_LONG])
    producer = _producer(monkeypatch=monkeypatch, bars={}, strategies=[strat])
    assert producer() == []


def test_origin_id_is_deterministic_per_bar(monkeypatch):
    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_LONG])
    producer = _producer(
        monkeypatch=monkeypatch,
        bars={"AAPL": _bars([100, 101])},
        strategies=[strat],
    )
    first = producer()[0].origin_id
    second = producer()[0].origin_id
    assert first == second
