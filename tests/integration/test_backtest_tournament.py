"""End-to-end integration: run a mini tournament on synthetic bars.

Skipped if ``vectorbt`` isn't available (it's a heavy optional transitive).
This test is the Phase-1 completion gate for the backtest tier (plan §17).
"""

from __future__ import annotations

import pytest

vbt = pytest.importorskip("vectorbt")

from src.backtest.tournament import run_tournament  # noqa: E402
from src.backtest.vectorbt_runner import BacktestConfig, run_backtest  # noqa: E402
from src.signals.strategies import REGISTRY  # noqa: E402
from src.signals.strategies.trend_following import TrendFollowing  # noqa: E402
from tests.fixtures.synthetic_bars import random_walk_bars, trending_bars  # noqa: E402


def test_single_backtest_produces_equity_curve():
    bars = {"SYN": trending_bars(n=500)}
    result = run_backtest(TrendFollowing(), bars, BacktestConfig())
    assert not result.equity_curve.empty
    assert "sharpe" in result.stats
    assert result.equity_curve.iloc[0] > 0


def test_tournament_ranks_all_strategies():
    bars = {
        "A": trending_bars(n=800, seed=1),
        "B": random_walk_bars(n=800, seed=2),
        "C": trending_bars(n=800, seed=3),
    }
    result = run_tournament(
        list(REGISTRY.values()),
        bars,
        train_months=6,
        test_months=3,
        mc_sims=500,
    )
    assert len(result.entries) == len(REGISTRY)
    lb = result.leaderboard()
    assert list(lb.columns)[0] == "strategy"
    # Composite should be sorted descending.
    assert lb["composite"].is_monotonic_decreasing
