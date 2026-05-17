"""Adapter: bars + Phase-1 strategies → list[SignalIntent].

Reads recent bars from the local cache (the seed_bars script is the producer
of that cache), runs each strategy, and converts the *transition on the most
recent bar* into an entry/exit intent the order manager can consume.

Stop-price policy (v1, simple): a fixed percent below the entry. The Phase-1
strategy interface only emits action + confidence — it doesn't volunteer a
stop. For ATR-based stops, plumb that through the strategy interface in a
later phase.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from src.backtest.data_loader import load_bars
from src.execution.order_manager import SignalIntent
from src.logging import get_logger
from src.persistence.models import Timeframe
from src.signals.strategies.base import ACTION_LONG, BaseStrategy

log = get_logger(__name__)


@dataclass(slots=True)
class ProducerConfig:
    universe: list[str]
    strategies: list[BaseStrategy]
    timeframe: Timeframe = Timeframe.DAY
    lookback_days: int = 200
    stop_pct: float = 0.05  # 5% below entry
    target_pct: float | None = None  # None = no take-profit leg


class SignalProducer:
    """Callable: returns the entry/exit intents implied by the latest bar."""

    def __init__(
        self, cfg: ProducerConfig, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self._cfg = cfg
        self._now = now or (lambda: datetime.now(UTC))

    def __call__(self) -> list[SignalIntent]:
        end = self._now()
        start = end - timedelta(days=self._cfg.lookback_days)
        bars = load_bars(self._cfg.universe, start, end, self._cfg.timeframe)
        if not bars:
            log.warning("signal_producer.no_bars", universe=self._cfg.universe[:5])
            return []

        intents: list[SignalIntent] = []
        for strat in self._cfg.strategies:
            for symbol, df in bars.items():
                if len(df) < strat.required_history_bars():
                    continue
                intent = self._intent_for(strat, symbol, df)
                if intent is not None:
                    intents.append(intent)
        log.info("signal_producer.run", universe=len(bars), intents=len(intents))
        return intents

    def _intent_for(
        self, strat: BaseStrategy, symbol: str, df: pd.DataFrame
    ) -> SignalIntent | None:
        signals = strat.generate_signals(df)
        if signals.empty or len(signals) < 2:
            return None

        last = signals.iloc[-1]
        prev = signals.iloc[-2]
        last_action = str(last["action"])
        prev_action = str(prev["action"])

        is_entry = last_action == ACTION_LONG and prev_action != ACTION_LONG
        is_exit = last_action != ACTION_LONG and prev_action == ACTION_LONG
        if not (is_entry or is_exit):
            return None

        last_close = Decimal(str(df["close"].iloc[-1]))
        stop = last_close * (Decimal("1") - Decimal(str(self._cfg.stop_pct)))
        target = (
            last_close * (Decimal("1") + Decimal(str(self._cfg.target_pct)))
            if self._cfg.target_pct is not None
            else None
        )

        bar_ts = df.index[-1]
        strategy_name = f"{strat.name}@{strat.version}"
        # Deterministic per (strategy, symbol, bar) so re-runs of the same bar
        # collapse to the same client_order_id downstream.
        origin_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{strategy_name}:{symbol}:{bar_ts}")
        )
        return SignalIntent(
            symbol=symbol,
            is_entry=is_entry,
            is_exit=is_exit,
            entry_price=last_close,
            stop_price=stop if is_entry else Decimal("0"),
            target_price=target if is_entry else None,
            strategy_name=strategy_name,
            origin_id=origin_id,
        )
