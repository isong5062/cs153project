import pandas as pd
import pytest

from app.engine.performance.metrics import (
    max_drawdown,
    sharpe_ratio,
    summarize,
    total_return,
    win_rate,
)


def test_total_return():
    assert total_return(pd.Series([100.0, 110.0])) == pytest.approx(0.10)


def test_max_drawdown():
    assert max_drawdown(pd.Series([100.0, 120.0, 90.0, 100.0])) == pytest.approx(-0.25)


def test_sharpe_zero_std_is_zero():
    assert sharpe_ratio(pd.Series([0.001] * 10)) == 0.0


def test_win_rate_ignores_zero():
    assert win_rate(pd.Series([0.01, -0.01, 0.02, 0.0])) == pytest.approx(2 / 3)


def test_summarize_keys():
    s = summarize(pd.Series([0.01, -0.02, 0.03, 0.0]))
    assert set(s) == {"total_return", "sharpe", "max_drawdown", "win_rate", "n_periods"}
