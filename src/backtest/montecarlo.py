"""Monte Carlo on a strategy's daily returns (plan §9.3).

Bootstrap the realized OOS daily return series N times and compute the
distribution of final equity, Sharpe, and max drawdown. The 5th-percentile
drawdown is what promotion gates on — a strategy that *could* have blown up
even if it didn't this once doesn't get promoted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    n_sims: int
    final_equity_mean: float
    final_equity_p05: float
    final_equity_p50: float
    final_equity_p95: float
    max_drawdown_mean: float
    max_drawdown_p05: float
    max_drawdown_p50: float
    sharpe_mean: float
    sharpe_p05: float


def _sim_stats(returns: np.ndarray, periods_per_year: int) -> tuple[float, float, float]:
    equity = np.cumprod(1 + returns)
    final = float(equity[-1])
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(dd.min())
    mean = returns.mean() * periods_per_year
    std = returns.std(ddof=0) * np.sqrt(periods_per_year)
    sharpe = float(mean / std) if std > 0 else 0.0
    return final, max_dd, sharpe


def monte_carlo_returns(
    returns: pd.Series,
    n_sims: int = 10_000,
    periods_per_year: int = 252,
    seed: int | None = 42,
) -> MonteCarloResult:
    """IID bootstrap of the daily return series (plan §9.3).

    Uses ``with-replacement`` sampling at the original length. Order is scrambled —
    this breaks any autocorrelation structure, which is the point: we want the
    distribution of *samples drawn from the same return-generating process*, not
    a reshuffle that preserves runs.
    """
    r = returns.dropna().to_numpy()
    if r.size < 30:  # need a minimum sample for MC to be meaningful
        return MonteCarloResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    rng = np.random.default_rng(seed)
    length = len(r)
    # Draw (n_sims, length) indices in one shot — much faster than a loop.
    idx = rng.integers(0, length, size=(n_sims, length))
    samples = r[idx]

    finals = np.empty(n_sims)
    max_dds = np.empty(n_sims)
    sharpes = np.empty(n_sims)
    for i in range(n_sims):
        finals[i], max_dds[i], sharpes[i] = _sim_stats(samples[i], periods_per_year)

    return MonteCarloResult(
        n_sims=n_sims,
        final_equity_mean=float(finals.mean()),
        final_equity_p05=float(np.percentile(finals, 5)),
        final_equity_p50=float(np.percentile(finals, 50)),
        final_equity_p95=float(np.percentile(finals, 95)),
        max_drawdown_mean=float(max_dds.mean()),
        max_drawdown_p05=float(np.percentile(max_dds, 5)),  # worst-case tail
        max_drawdown_p50=float(np.percentile(max_dds, 50)),
        sharpe_mean=float(sharpes.mean()),
        sharpe_p05=float(np.percentile(sharpes, 5)),
    )
