"""Sanity tests for the indicator helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.indicators import adx, atr, bollinger, donchian, ema, rsi


def _close(series: list[float]) -> pd.Series:
    return pd.Series(series, dtype=float)


def test_rsi_range():
    close = _close(list(np.linspace(100, 120, 50)) + list(np.linspace(120, 100, 50)))
    out = rsi(close, length=14).dropna()
    assert ((out >= 0) & (out <= 100)).all()


def test_ema_matches_pandas():
    close = _close(list(range(1, 51)))
    out = ema(close, length=10)
    expected = close.ewm(span=10, adjust=False, min_periods=10).mean()
    pd.testing.assert_series_equal(out, expected, check_names=False)


def test_bollinger_bands_order():
    close = _close(list(np.random.default_rng(0).normal(100, 2, size=100)))
    lower, mid, upper = bollinger(close, length=20, n_std=2.0)
    dropped = pd.concat([lower, mid, upper], axis=1).dropna()
    assert (dropped.iloc[:, 0] <= dropped.iloc[:, 1]).all()
    assert (dropped.iloc[:, 1] <= dropped.iloc[:, 2]).all()


def test_atr_nonneg():
    rng = np.random.default_rng(1)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    high = close + np.abs(rng.normal(0, 0.5, 200))
    low = close - np.abs(rng.normal(0, 0.5, 200))
    out = atr(high, low, close, length=14).dropna()
    assert (out >= 0).all()


def test_adx_range():
    rng = np.random.default_rng(2)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))
    high = close + np.abs(rng.normal(0, 0.5, 300))
    low = close - np.abs(rng.normal(0, 0.5, 300))
    out = adx(high, low, close, length=14).dropna()
    assert ((out >= 0) & (out <= 100)).all()


def test_donchian_contains_prices():
    rng = np.random.default_rng(3)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    high = close + 1
    low = close - 1
    lower, upper = donchian(high, low, length=20)
    merged = pd.concat([lower, upper, high, low], axis=1).dropna()
    lo, hi, hh, ll = merged.iloc[:, 0], merged.iloc[:, 1], merged.iloc[:, 2], merged.iloc[:, 3]
    assert (hi >= hh).all()
    assert (lo <= ll).all()
