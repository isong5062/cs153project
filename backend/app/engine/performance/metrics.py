"""Performance metrics computed from equity curves / return series."""

from __future__ import annotations

import numpy as np
import pandas as pd


def equity_from_returns(returns: pd.Series, start: float = 1.0) -> pd.Series:
    return start * (1.0 + returns.fillna(0.0)).cumprod()


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    std = r.std(ddof=1)
    if not np.isfinite(std) or std < 1e-12:  # treat (near-)zero variance as no signal
        return 0.0
    return float(r.mean() / std * np.sqrt(periods_per_year))


def win_rate(returns: pd.Series) -> float:
    r = returns.dropna()
    nz = r[r != 0]
    if nz.empty:
        return 0.0
    return float((nz > 0).mean())


def summarize(returns: pd.Series, periods_per_year: int = 252) -> dict:
    equity = equity_from_returns(returns)
    return {
        "total_return": total_return(equity),
        "sharpe": sharpe_ratio(returns, periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "win_rate": win_rate(returns),
        "n_periods": int(returns.dropna().shape[0]),
    }
