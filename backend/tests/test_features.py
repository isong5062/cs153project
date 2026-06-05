import numpy as np
import pandas as pd
import pytest

from app.engine.features.engineering import compute_features, validate_bars
from app.engine.features.indicators import sma
from tests.factories import make_ohlcv


def test_sma_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = sma(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_features_no_lookahead():
    """Features computed on a prefix must equal those from the full series."""
    df = make_ohlcv(n=300, seed=7)
    k = 200
    full = compute_features(df)
    part = compute_features(df.iloc[:k])
    pd.testing.assert_frame_equal(full.iloc[:k], part, check_exact=False, atol=1e-9)


def test_validate_bars_ok_and_bad():
    df = make_ohlcv(n=50)
    validate_bars(df)  # should not raise

    bad = df.copy()
    bad.iloc[10, bad.columns.get_loc("high")] = bad.iloc[10]["low"] - 1.0
    with pytest.raises(ValueError):
        validate_bars(bad)
