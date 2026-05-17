"""Walk-forward validation (plan §9.1).

Split history into rolling ``train`` / ``test`` windows. For each fold:
  1. Pick the best parameter set from ``strategy.param_grid`` on train by Sharpe.
  2. Re-run those params on the test window (unseen).
  3. Concatenate test-window returns across folds for the OOS equity curve.

OOS metrics (Sharpe, MDD, etc.) are computed on that concatenated series — this
is the "survived the walk-forward" result the tournament ranks on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

from src.backtest.vectorbt_runner import (
    BacktestConfig,
    BacktestResult,
    _summary_stats,
    run_backtest,
)
from src.signals.strategies.base import BaseStrategy


@dataclass
class WalkForwardFold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict[str, Any]
    train_sharpe: float
    test_result: BacktestResult


@dataclass
class WalkForwardResult:
    strategy_name: str
    strategy_version: str
    folds: list[WalkForwardFold] = field(default_factory=list)
    oos_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    oos_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    oos_stats: dict[str, float] = field(default_factory=dict)


def _slice_bars(
    bars: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, pd.DataFrame]:
    return {s: df.loc[(df.index >= start) & (df.index <= end)] for s, df in bars.items()}


def _enumerate_params(strategy_cls: type[BaseStrategy]) -> list[dict[str, Any]]:
    grid = list(strategy_cls.param_grid) if strategy_cls.param_grid else []
    if not grid:
        grid = [dict(strategy_cls.default_params)]
    return grid


def walk_forward(
    strategy_cls: type[BaseStrategy],
    bars: dict[str, pd.DataFrame],
    *,
    train_months: int = 12,
    test_months: int = 3,
    config: BacktestConfig | None = None,
) -> WalkForwardResult:
    """Run walk-forward across the union date range of ``bars``."""
    all_dates = sorted({ts for df in bars.values() for ts in df.index})
    if not all_dates:
        return WalkForwardResult(strategy_cls.name, strategy_cls.version)

    start, end = pd.Timestamp(all_dates[0]), pd.Timestamp(all_dates[-1])
    train_delta = timedelta(days=int(train_months * 30.44))
    test_delta = timedelta(days=int(test_months * 30.44))

    folds: list[WalkForwardFold] = []
    oos_returns_parts: list[pd.Series] = []

    cursor = start
    while cursor + train_delta + test_delta <= end:
        train_s, train_e = cursor, cursor + train_delta
        test_s, test_e = train_e, train_e + test_delta

        train_bars = _slice_bars(bars, train_s, train_e)
        test_bars = _slice_bars(bars, test_s, test_e)

        best_params: dict[str, Any] | None = None
        best_sharpe = float("-inf")
        for params in _enumerate_params(strategy_cls):
            cand = strategy_cls(params=dict(params))
            res = run_backtest(cand, train_bars, config)
            sharpe = res.stats.get("sharpe", 0.0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = dict(params)

        final = strategy_cls(params=dict(best_params or {}))
        test_res = run_backtest(final, test_bars, config)

        folds.append(
            WalkForwardFold(
                train_start=train_s,
                train_end=train_e,
                test_start=test_s,
                test_end=test_e,
                best_params=best_params or {},
                train_sharpe=best_sharpe if best_sharpe != float("-inf") else 0.0,
                test_result=test_res,
            )
        )
        if not test_res.returns.empty:
            oos_returns_parts.append(test_res.returns)

        cursor = test_e  # non-overlapping test windows (purged walk-forward lite)

    if not oos_returns_parts:
        return WalkForwardResult(strategy_cls.name, strategy_cls.version, folds)

    oos_returns = pd.concat(oos_returns_parts).sort_index()
    # Drop duplicate dates at fold boundaries (keep first).
    oos_returns = oos_returns[~oos_returns.index.duplicated(keep="first")]
    oos_equity = (1 + oos_returns).cumprod()
    oos_stats = _summary_stats(oos_equity, oos_returns, (config or BacktestConfig()).freq)

    return WalkForwardResult(
        strategy_name=strategy_cls.name,
        strategy_version=strategy_cls.version,
        folds=folds,
        oos_returns=oos_returns,
        oos_equity=oos_equity,
        oos_stats=oos_stats,
    )
