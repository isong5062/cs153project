"""Smoke test for the full Phase-2 loop without Postgres or Alpaca.

Wires SignalProducer + OrderManager + TradingScheduler against a
SimulatedBroker. Persistence calls are captured into an in-memory list so we
can assert what the scheduler would have written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

import pandas as pd

from src.broker.simulated import SimulatedBroker
from src.execution.order_manager import OrderManager, OrderOutcome, SignalIntent
from src.execution.signal_producer import ProducerConfig, SignalProducer
from src.scheduler.jobs import build_scheduler
from src.signals.strategies.base import ACTION_FLAT, ACTION_LONG, BaseStrategy


@dataclass
class _ScriptedStrategy(BaseStrategy):
    name: ClassVar[str] = "scripted_smoke"
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
            {"action": actions, "confidence": [0.5] * n}, index=data.index
        )


def _bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000] * len(closes)},
        index=idx,
    )


def test_one_pass_produces_signal_submits_order_and_invokes_recorders(monkeypatch):
    bars = {
        "AAPL": _bars([99, 100, 101]),  # entry on last bar
        "MSFT": _bars([400, 401, 402]),  # entry on last bar
    }
    monkeypatch.setattr(
        "src.execution.signal_producer.load_bars",
        lambda symbols, start, end, timeframe: {s: bars[s] for s in symbols if s in bars},
    )

    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_FLAT, ACTION_LONG])
    producer = SignalProducer(
        ProducerConfig(
            universe=list(bars.keys()),
            strategies=[strat],
            stop_pct=0.05,
            lookback_days=10,
        )
    )

    broker = SimulatedBroker(starting_cash=100_000)
    for sym, df in bars.items():
        broker.set_mark(sym, float(df["close"].iloc[-1]))

    om = OrderManager(
        broker=broker,
        risk_per_trade_pct=0.01,
        max_position_pct=0.05,
        max_concurrent_positions=10,
        daily_loss_limit_pct=0.02,
        max_drawdown_pct=0.08,
    )

    captured_outcomes: list[tuple[list[SignalIntent], list[OrderOutcome]]] = []
    captured_equity: list[tuple[Decimal, Decimal]] = []

    sched = build_scheduler(
        broker, om, producer,
        record_equity=lambda eq, pnl: captured_equity.append((eq, pnl)),
        record_outcomes=lambda intents, outs: captured_outcomes.append((intents, outs)),
    )

    # Drive the same callbacks the cron triggers would:
    sched.pre_market()
    sched.generate_and_submit()
    sched.manage_intraday()

    # Producer emitted 2 entries; both should have submitted.
    assert len(captured_outcomes) == 1
    intents, outcomes = captured_outcomes[0]
    assert {i.symbol for i in intents} == {"AAPL", "MSFT"}
    assert all(o.submitted for o in outcomes)

    # Both positions opened.
    syms = {p.symbol for p in broker.get_positions()}
    assert syms == {"AAPL", "MSFT"}

    # Equity recorded.
    assert len(captured_equity) == 1


def test_loop_records_rejected_signal_when_guard_blocks(monkeypatch):
    bars = {"AAPL": _bars([100, 101, 102])}
    monkeypatch.setattr(
        "src.execution.signal_producer.load_bars",
        lambda symbols, start, end, timeframe: {s: bars[s] for s in symbols if s in bars},
    )
    strat = _ScriptedStrategy(actions=[ACTION_FLAT, ACTION_FLAT, ACTION_LONG])
    producer = SignalProducer(
        ProducerConfig(universe=["AAPL"], strategies=[strat], stop_pct=0.05, lookback_days=10)
    )

    broker = SimulatedBroker(starting_cash=100_000)
    broker.set_mark("AAPL", 102)

    om = OrderManager(
        broker=broker,
        risk_per_trade_pct=0.01,
        max_position_pct=0.05,
        max_concurrent_positions=10,
        daily_loss_limit_pct=0.02,
        max_drawdown_pct=0.001,  # absurdly tight; almost any peak triggers it
    )

    captured: list = []
    sched = build_scheduler(
        broker, om, producer,
        record_outcomes=lambda intents, outs: captured.append((intents, outs)),
    )
    # Set peak above current equity so drawdown guard trips.
    sched._tracker.peak = Decimal("200000")
    sched._tracker.day_start = Decimal("100000")
    sched.generate_and_submit()

    intents, outcomes = captured[0]
    assert outcomes[0].submitted is False
    assert outcomes[0].guard is not None
    assert outcomes[0].guard.guard == "drawdown"
    assert broker.get_position("AAPL") is None
