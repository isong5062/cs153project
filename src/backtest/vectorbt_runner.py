"""Vectorbt-backed backtest runner (plan §8, Tier 1).

Takes a strategy and a dict of per-symbol bars, generates entries/exits, and
hands them to ``vbt.Portfolio.from_signals`` with realistic fees + slippage.
Outputs a :class:`BacktestResult` with equity curve and summary stats.

Fee model (plan §8): Alpaca commission is 0, but SEC/TAF fees are ~0.3 bps
per share. We model the combined friction as ``fees`` in bps on notional.
Slippage defaults to 5 bps — conservative for liquid large-caps on market-open
entries (the swing horizon default).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.signals.strategies.base import BaseStrategy, signals_to_entries_exits


@dataclass
class BacktestConfig:
    init_cash: float = 100_000.0
    fees_bps: float = 5.0             # 5 bps per fill on notional
    slippage_bps: float = 5.0         # 5 bps adverse fill
    position_pct: float = 0.10        # % of equity per entry (max 10 concurrent)
    freq: str = "1D"                  # pandas offset alias


@dataclass
class BacktestResult:
    strategy_name: str
    strategy_version: str
    params: dict[str, Any]
    start: pd.Timestamp
    end: pd.Timestamp
    equity_curve: pd.Series
    returns: pd.Series
    stats: dict[str, float] = field(default_factory=dict)
    num_trades: int = 0


def _build_signal_matrices(
    strategy: BaseStrategy, bars: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (close, entries, exits) as symbol-columned, date-aligned frames."""
    frames = {}
    for symbol, df in bars.items():
        if df.empty or len(df) < strategy.required_history_bars():
            continue
        sig = strategy.generate_signals(df)
        entries, exits = signals_to_entries_exits(sig)
        frames[symbol] = {
            "close": df["close"].astype(float),
            "entries": entries,
            "exits": exits,
        }

    if not frames:
        empty = pd.DataFrame()
        return empty, empty, empty

    close = pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()
    entries = pd.DataFrame(
        {s: f["entries"] for s, f in frames.items()}
    ).reindex(close.index).fillna(False).astype(bool)
    exits = pd.DataFrame(
        {s: f["exits"] for s, f in frames.items()}
    ).reindex(close.index).fillna(False).astype(bool)
    # Forward-fill close so vectorbt doesn't barf on sparse symbols.
    close = close.ffill()
    return close, entries, exits


def _summary_stats(equity: pd.Series, returns: pd.Series, freq: str) -> dict[str, float]:
    """Composite-score ingredients (plan §9.2): Sharpe, Calmar, MDD, turnover, win rate."""
    if equity.empty or returns.empty:
        return {}

    # Periods-per-year for a given freq (daily/hour/min).
    periods = {"1D": 252, "1H": 252 * 6.5, "1min": 252 * 390}.get(freq, 252)
    mean = returns.mean() * periods
    std = returns.std(ddof=0) * np.sqrt(periods)
    sharpe = float(mean / std) if std > 0 else 0.0

    downside = returns[returns < 0]
    dstd = downside.std(ddof=0) * np.sqrt(periods) if not downside.empty else 0.0
    sortino = float(mean / dstd) if dstd > 0 else 0.0

    running_peak = equity.cummax()
    drawdown = (equity - running_peak) / running_peak
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    cagr = (1 + total_return) ** (1 / years) - 1
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0

    return {
        "total_return": total_return,
        "cagr": float(cagr),
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "volatility": float(std),
    }


def run_backtest(
    strategy: BaseStrategy,
    bars: dict[str, pd.DataFrame],
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run a single backtest. Returns equity curve + stats. Empty input → empty result."""
    import vectorbt as vbt  # heavyweight import, defer

    cfg = config or BacktestConfig()
    close, entries, exits = _build_signal_matrices(strategy, bars)

    if close.empty:
        idx = pd.DatetimeIndex([], tz="UTC")
        return BacktestResult(
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            params=dict(strategy.params),
            start=pd.Timestamp.now(tz="UTC"),
            end=pd.Timestamp.now(tz="UTC"),
            equity_curve=pd.Series(dtype=float, index=idx),
            returns=pd.Series(dtype=float, index=idx),
            stats={},
            num_trades=0,
        )

    pf = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=exits,
        init_cash=cfg.init_cash,
        fees=cfg.fees_bps / 1e4,
        slippage=cfg.slippage_bps / 1e4,
        size=cfg.position_pct,
        size_type="percent",
        cash_sharing=True,
        group_by=True,
        freq=cfg.freq,
    )

    equity = pf.value()
    if isinstance(equity, pd.DataFrame):
        equity = equity.iloc[:, 0]
    equity = equity.rename("equity")
    returns = equity.pct_change().fillna(0.0).rename("returns")

    stats = _summary_stats(equity, returns, cfg.freq)

    try:
        trades = pf.trades
        num_trades = int(trades.count()) if hasattr(trades, "count") else int(len(trades.records))
    except Exception:
        num_trades = 0

    # Win rate (best-effort; some vectorbt versions differ on Trades API).
    try:
        win_rate = float(pf.trades.win_rate())
        stats["win_rate"] = win_rate
    except Exception:
        pass

    return BacktestResult(
        strategy_name=strategy.name,
        strategy_version=strategy.version,
        params=dict(strategy.params),
        start=close.index[0],
        end=close.index[-1],
        equity_curve=equity,
        returns=returns,
        stats=stats,
        num_trades=num_trades,
    )
