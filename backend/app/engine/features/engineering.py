"""Feature engineering + bar validation.

All features are causal: the value at time t depends only on bars up to t, so
computing on a truncated prefix yields identical values (verified in tests).
"""

from __future__ import annotations

import pandas as pd

from app.engine.features.indicators import (
    atr,
    log_returns,
    rolling_vol,
    rsi,
    sma,
    volume_zscore,
)

FEATURE_COLUMNS = [
    "log_return",
    "vol_20",
    "vol_60",
    "ret_5",
    "sma_ratio_50",
    "rsi_14",
    "atr_14",
    "volume_z_20",
]

# Subset used by the regime HMM (Phase 2).
REGIME_FEATURES = ["log_return", "vol_20", "volume_z_20"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    close, high, low, vol = bars["close"], bars["high"], bars["low"], bars["volume"]
    r = log_returns(close)

    feats = pd.DataFrame(index=bars.index)
    feats["log_return"] = r
    feats["vol_20"] = rolling_vol(r, 20)
    feats["vol_60"] = rolling_vol(r, 60)
    feats["ret_5"] = close.pct_change(5)
    feats["sma_ratio_50"] = close / sma(close, 50) - 1.0
    feats["rsi_14"] = rsi(close, 14)
    feats["atr_14"] = atr(high, low, close, 14)
    feats["volume_z_20"] = volume_zscore(vol, 20)
    return feats


def validate_bars(bars: pd.DataFrame) -> None:
    """Raise ValueError if the OHLCV frame is malformed."""
    if bars.empty:
        raise ValueError("no bars")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("timestamps not sorted ascending")
    if bars.index.has_duplicates:
        raise ValueError("duplicate timestamps")
    if (bars["high"] < bars["low"]).any():
        raise ValueError("high < low")
    if (bars["high"] < bars[["open", "close"]].max(axis=1)).any():
        raise ValueError("high < max(open, close)")
    if (bars["low"] > bars[["open", "close"]].min(axis=1)).any():
        raise ValueError("low > min(open, close)")
    if (bars["volume"] < 0).any():
        raise ValueError("negative volume")
