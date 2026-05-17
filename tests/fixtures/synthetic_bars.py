"""Synthetic OHLCV bar generators for deterministic backtest tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def random_walk_bars(
    n: int = 400,
    start: str = "2020-01-01",
    seed: int = 7,
    drift: float = 0.0005,
    vol: float = 0.015,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Geometric-random-walk daily bars. Deterministic given ``seed``."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=drift, scale=vol, size=n)
    close = start_price * np.exp(np.cumsum(rets))
    # Construct high/low/open from the close path with plausible intra-day range.
    daily_range = np.abs(rng.normal(0.0, vol, size=n)) * close
    open_ = np.concatenate([[start_price], close[:-1]])
    high = np.maximum(open_, close) + daily_range / 2
    low = np.minimum(open_, close) - daily_range / 2
    volume = rng.integers(500_000, 5_000_000, size=n).astype("int64")

    idx = pd.date_range(start=start, periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def trending_bars(n: int = 400, seed: int = 3) -> pd.DataFrame:
    return random_walk_bars(n=n, seed=seed, drift=0.0015, vol=0.012)


def mean_reverting_bars(n: int = 400, seed: int = 11) -> pd.DataFrame:
    """Ornstein-Uhlenbeck-ish path around 100 for mean-reversion tests."""
    rng = np.random.default_rng(seed)
    price = np.zeros(n)
    price[0] = 100.0
    theta, mu, sigma = 0.1, 100.0, 1.5
    for i in range(1, n):
        price[i] = price[i - 1] + theta * (mu - price[i - 1]) + rng.normal(0, sigma)

    close = price
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, size=n))
    volume = rng.integers(500_000, 5_000_000, size=n).astype("int64")
    idx = pd.date_range(start="2020-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
