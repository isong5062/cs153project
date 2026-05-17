"""Compute live-trading metrics from ``equity_curve`` and ``trades``.

Backtest metrics live in ``src.backtest`` and are produced by vectorbt against
synthetic equity series. The live equivalents have to read from Postgres and
deal with sparse, irregularly-spaced snapshots (one EOD row + occasional
intraday ticks). Annualization assumes 252 trading days regardless of sample
spacing — close enough for the paper-week gate; the backtest tier is the
authority for production-grade Sharpe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persistence.models import EquitySnapshot, Trade, TradeStatus

TRADING_DAYS_PER_YEAR = 252


@dataclass(slots=True)
class LiveMetrics:
    """Snapshot of live-trading performance over a window."""

    window_start: datetime | None
    window_end: datetime | None
    n_snapshots: int
    starting_equity: Decimal
    ending_equity: Decimal
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_annualized: float | None  # None if <2 daily returns
    n_closed_trades: int
    win_rate: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    profit_factor: float | None  # gross_wins / gross_losses, None if no losses


def equity_to_returns(equity: list[Decimal]) -> list[float]:
    """Daily simple returns from an ordered equity series."""
    out: list[float] = []
    for prev, curr in zip(equity, equity[1:]):
        if prev == 0:
            continue
        out.append(float((curr - prev) / prev))
    return out


def _max_drawdown(equity: list[Decimal]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = float((v - peak) / peak)
            if dd < worst:
                worst = dd
    return worst  # negative number


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = sqrt(var)
    if std == 0:
        return None
    return (mean / std) * sqrt(TRADING_DAYS_PER_YEAR)


def _equity_series(
    session: Session,
    *,
    broker_mode: str,
    start: datetime | None,
    end: datetime | None,
) -> list[EquitySnapshot]:
    stmt = select(EquitySnapshot).where(EquitySnapshot.broker_mode == broker_mode)
    if start is not None:
        stmt = stmt.where(EquitySnapshot.ts >= start)
    if end is not None:
        stmt = stmt.where(EquitySnapshot.ts <= end)
    stmt = stmt.order_by(EquitySnapshot.ts.asc())
    return list(session.execute(stmt).scalars())


def _closed_trades(
    session: Session, *, start: datetime | None, end: datetime | None
) -> list[Trade]:
    stmt = select(Trade).where(Trade.status == TradeStatus.CLOSED)
    if start is not None:
        stmt = stmt.where(Trade.exit_ts >= start)
    if end is not None:
        stmt = stmt.where(Trade.exit_ts <= end)
    return list(session.execute(stmt).scalars())


def compute_live_metrics(
    session: Session,
    *,
    broker_mode: str = "paper",
    start: datetime | None = None,
    end: datetime | None = None,
) -> LiveMetrics:
    snapshots = _equity_series(session, broker_mode=broker_mode, start=start, end=end)
    trades = _closed_trades(session, start=start, end=end)

    if not snapshots:
        return LiveMetrics(
            window_start=start,
            window_end=end,
            n_snapshots=0,
            starting_equity=Decimal(0),
            ending_equity=Decimal(0),
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_annualized=None,
            n_closed_trades=len(trades),
            win_rate=None,
            avg_win_pct=None,
            avg_loss_pct=None,
            profit_factor=None,
        )

    equity_series = [s.equity for s in snapshots]
    starting = equity_series[0]
    ending = equity_series[-1]
    total_return = (
        float((ending - starting) / starting) if starting != 0 else 0.0
    )
    returns = equity_to_returns(equity_series)
    sharpe = _sharpe(returns)
    mdd = _max_drawdown(equity_series)

    # Trade-level stats
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    profit_factor: float | None = None
    if trades:
        pnl_pcts = [float(t.pnl_pct) for t in trades if t.pnl_pct is not None]
        if pnl_pcts:
            wins = [p for p in pnl_pcts if p > 0]
            losses = [p for p in pnl_pcts if p < 0]
            win_rate = len(wins) / len(pnl_pcts)
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
            gross_wins = sum(wins)
            gross_losses = -sum(losses)
            profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None

    return LiveMetrics(
        window_start=snapshots[0].ts,
        window_end=snapshots[-1].ts,
        n_snapshots=len(snapshots),
        starting_equity=starting,
        ending_equity=ending,
        total_return_pct=total_return,
        max_drawdown_pct=mdd,
        sharpe_annualized=sharpe,
        n_closed_trades=len(trades),
        win_rate=win_rate,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        profit_factor=profit_factor,
    )
