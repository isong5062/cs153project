"""Monte Carlo module smoke + property tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.montecarlo import monte_carlo_returns


def test_mc_zero_for_flat_returns():
    returns = pd.Series(np.zeros(300))
    mc = monte_carlo_returns(returns, n_sims=500)
    assert mc.sharpe_mean == 0.0
    assert mc.max_drawdown_p05 == 0.0
    assert mc.final_equity_mean == 1.0


def test_mc_percentile_ordering():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0005, 0.01, size=500))
    mc = monte_carlo_returns(returns, n_sims=2000, seed=0)
    # p05 must be ≤ p50 ≤ p95 by construction.
    assert mc.final_equity_p05 <= mc.final_equity_p50 <= mc.final_equity_p95
    # p05 drawdown is the *worst* tail (most negative).
    assert mc.max_drawdown_p05 <= mc.max_drawdown_p50


def test_mc_skips_on_tiny_series():
    mc = monte_carlo_returns(pd.Series([0.01, -0.01]), n_sims=100)
    assert mc.n_sims == 0
