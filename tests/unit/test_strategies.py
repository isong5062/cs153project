"""Property + golden tests for the three baseline strategies.

Invariants (plan §12):
- Output frame shape: columns [action, confidence] and index == input index.
- Action values ⊂ {long, flat, short}; confidence ∈ [0, 1].
- Never emit conflicting signals on the same bar (can't be both long and short).
- Signals are deterministic given the same input.
"""

from __future__ import annotations

import pytest

from src.signals.strategies import REGISTRY
from src.signals.strategies.base import VALID_ACTIONS, signals_to_entries_exits
from tests.fixtures.synthetic_bars import mean_reverting_bars, random_walk_bars, trending_bars


@pytest.mark.parametrize("strategy_cls", list(REGISTRY.values()))
def test_output_schema(strategy_cls):
    bars = random_walk_bars(n=300, seed=1)
    strat = strategy_cls()
    sig = strat.generate_signals(bars)

    assert list(sig.columns[:2]) == ["action", "confidence"]
    assert sig.index.equals(bars.index)
    assert set(sig["action"].dropna().unique()) <= VALID_ACTIONS
    conf = sig["confidence"].dropna()
    assert ((conf >= 0) & (conf <= 1)).all()


@pytest.mark.parametrize("strategy_cls", list(REGISTRY.values()))
def test_determinism(strategy_cls):
    bars = random_walk_bars(n=300, seed=2)
    a = strategy_cls().generate_signals(bars)
    b = strategy_cls().generate_signals(bars)
    assert a.equals(b)


@pytest.mark.parametrize("strategy_cls", list(REGISTRY.values()))
def test_no_conflicting_signals_per_bar(strategy_cls):
    bars = random_walk_bars(n=300, seed=9)
    sig = strategy_cls().generate_signals(bars)
    # v1 is long-only; ensure we don't accidentally mix long+short on same bar.
    # This is trivially true per-bar since action is a single cell, but we also
    # check that entries/exits are not simultaneously True.
    entries, exits = signals_to_entries_exits(sig)
    assert not (entries & exits).any()


def test_trend_strategy_holds_in_uptrend():
    bars = trending_bars(n=500)
    from src.signals.strategies.trend_following import TrendFollowing

    sig = TrendFollowing().generate_signals(bars)
    # In a strong drifting uptrend, expect non-trivial time spent long.
    frac_long = (sig["action"] == "long").mean()
    assert frac_long > 0.1


def test_mean_reversion_produces_some_entries_on_mr_series():
    bars = mean_reverting_bars(n=500)
    from src.signals.strategies.mean_reversion import MeanReversion

    sig = MeanReversion().generate_signals(bars)
    entries, _ = signals_to_entries_exits(sig)
    assert entries.sum() >= 1


def test_empty_input_returns_empty_frame():
    import pandas as pd

    from src.signals.strategies.mean_reversion import MeanReversion

    empty = pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([], tz="UTC"),
    )
    sig = MeanReversion().generate_signals(empty)
    assert sig.empty
