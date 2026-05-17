"""Unit tests for live-trading metrics.

These exercise the pure helpers (no DB) since the equity-from-DB path is
trivial SQL and is covered by integration tests once a paper week is recorded.
"""

from __future__ import annotations

from decimal import Decimal
from math import isclose

import pytest

from src.metrics.live import (
    TRADING_DAYS_PER_YEAR,
    _max_drawdown,
    _sharpe,
    equity_to_returns,
)


def test_equity_to_returns_basic():
    eq = [Decimal("100"), Decimal("110"), Decimal("99")]
    rets = equity_to_returns(eq)
    assert isclose(rets[0], 0.10)
    assert isclose(rets[1], -0.10)


def test_equity_to_returns_skips_zero_prev():
    eq = [Decimal("0"), Decimal("100"), Decimal("110")]
    rets = equity_to_returns(eq)
    # First step skipped (prev == 0); only one valid return.
    assert len(rets) == 1
    assert isclose(rets[0], 0.10)


def test_max_drawdown_monotonic_up_is_zero():
    eq = [Decimal(x) for x in (100, 101, 102, 103)]
    assert _max_drawdown(eq) == 0.0


def test_max_drawdown_captures_peak_to_trough():
    eq = [Decimal(x) for x in (100, 120, 90, 110)]
    # Peak 120 → trough 90 = -25%
    assert isclose(_max_drawdown(eq), -0.25)


def test_max_drawdown_empty():
    assert _max_drawdown([]) == 0.0


def test_sharpe_none_for_constant_returns():
    # Zero std dev → Sharpe undefined.
    assert _sharpe([0.001, 0.001, 0.001]) is None


def test_sharpe_none_for_too_few_samples():
    assert _sharpe([0.01]) is None
    assert _sharpe([]) is None


def test_sharpe_positive_for_positive_drift():
    # Mean > 0, finite std → positive Sharpe.
    rets = [0.01, -0.005, 0.015, 0.0, 0.02, -0.01, 0.012]
    s = _sharpe(rets)
    assert s is not None
    assert s > 0


def test_sharpe_annualization_factor():
    # Construct returns where mean/std == 1; Sharpe should equal sqrt(252).
    import math
    rets = [1.0, -1.0, 1.0, -1.0]  # mean=0 — degenerate. Use shifted set:
    rets = [2.0, 0.0, 2.0, 0.0]    # mean=1, var=4/3, std=√(4/3)
    s = _sharpe(rets)
    assert s is not None
    expected = (1.0 / math.sqrt(4.0 / 3.0)) * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert isclose(s, expected, rel_tol=1e-9)
