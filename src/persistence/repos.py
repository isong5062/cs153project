"""Repository layer: persists the live-trading loop's state.

Why a single module, not a package: only four entities are touched by the
trading loop right now (Strategy, Signal, Trade, EquitySnapshot) — splitting
into one-class-per-file would be ceremony without payoff. Reflection / agent
runs land in their own modules in later phases.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.broker.base import OrderSide
from src.config import BrokerMode, get_settings
from src.execution.order_manager import OrderOutcome, SignalIntent
from src.persistence.models import (
    EquitySnapshot,
    Signal,
    SignalAction,
    SignalStatus,
    Strategy,
    Trade,
    TradeSide,
    TradeStatus,
)
from src.signals.strategies.base import BaseStrategy

# ── Strategies ──────────────────────────────────────────────────────────────


def upsert_strategies(
    session: Session, strategies: list[BaseStrategy]
) -> dict[str, uuid.UUID]:
    """Ensure each strategy has a row. Returns ``{name@version: id}``.

    Idempotent: re-running with the same set yields the same ids.
    """
    out: dict[str, uuid.UUID] = {}
    for s in strategies:
        key = f"{s.name}@{s.version}"
        existing = session.execute(
            select(Strategy).where(Strategy.name == s.name, Strategy.version == s.version)
        ).scalar_one_or_none()
        if existing is None:
            row = Strategy(
                name=s.name, version=s.version, params=dict(s.params), enabled=True
            )
            session.add(row)
            session.flush()
            out[key] = row.id
        else:
            out[key] = existing.id
    return out


# ── Signals ────────────────────────────────────────────────────────────────


def _action_for(intent: SignalIntent) -> SignalAction:
    if intent.is_exit:
        return SignalAction.EXIT
    if intent.is_entry:
        return SignalAction.LONG
    return SignalAction.FLAT


def _status_for(outcome: OrderOutcome) -> tuple[SignalStatus, str | None]:
    if outcome.submitted:
        return SignalStatus.EXECUTED, None
    if outcome.guard is not None and outcome.guard.verdict.value == "reject":
        return SignalStatus.REJECTED_BY_RISK, f"{outcome.guard.guard}: {outcome.guard.reason}"
    if outcome.error:
        return SignalStatus.EXECUTION_FAILED, outcome.error
    return SignalStatus.GENERATED, "; ".join(outcome.notes) or None


def record_signal(
    session: Session,
    *,
    intent: SignalIntent,
    outcome: OrderOutcome,
    strategy_id: uuid.UUID,
    trace_id: uuid.UUID | None = None,
) -> uuid.UUID:
    status, reason = _status_for(outcome)
    sig = Signal(
        strategy_id=strategy_id,
        symbol=intent.symbol,
        ts=datetime.now(UTC),
        action=_action_for(intent),
        confidence=None,
        entry_price_hint=intent.entry_price,
        stop_price_hint=intent.stop_price if intent.is_entry else None,
        target_price_hint=intent.target_price,
        status=status,
        rejection_reason=reason,
        trace_id=trace_id,
    )
    session.add(sig)
    session.flush()
    return sig.id


# ── Trades ─────────────────────────────────────────────────────────────────


def record_trade_open(
    session: Session,
    *,
    intent: SignalIntent,
    outcome: OrderOutcome,
    strategy_id: uuid.UUID,
    signal_id: uuid.UUID,
    trace_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert an OPEN trade row for an entry that filled. Returns the trade id,
    or None if the outcome did not result in a trade."""
    order = outcome.order
    if not outcome.submitted or order is None or outcome.qty <= 0:
        return None

    settings = get_settings()
    side = TradeSide.LONG if order.side == OrderSide.BUY else TradeSide.SHORT
    fill_price = order.avg_fill_price or intent.entry_price

    trade = Trade(
        strategy_id=strategy_id,
        signal_id=signal_id,
        symbol=intent.symbol,
        side=side,
        qty=Decimal(outcome.qty),
        entry_ts=order.filled_at or order.submitted_at,
        entry_price=fill_price,
        stop_price=intent.stop_price if intent.is_entry else None,
        target_price=intent.target_price,
        status=TradeStatus.OPEN,
        broker_order_id=order.id,
        client_order_id=order.client_order_id,
        trace_id=trace_id,
        broker_mode=BrokerMode.PAPER.value
        if settings.broker_mode == BrokerMode.PAPER
        else BrokerMode.LIVE.value,
    )
    session.add(trade)
    session.flush()
    return trade.id


def close_trade(
    session: Session,
    *,
    symbol: str,
    exit_price: Decimal,
    exit_ts: datetime,
) -> uuid.UUID | None:
    """Close the most-recent OPEN trade for a symbol; return its id or None."""
    open_trade = session.execute(
        select(Trade)
        .where(Trade.symbol == symbol, Trade.status == TradeStatus.OPEN)
        .order_by(Trade.entry_ts.desc())
    ).scalars().first()
    if open_trade is None:
        return None
    open_trade.exit_ts = exit_ts
    open_trade.exit_price = exit_price
    open_trade.status = TradeStatus.CLOSED
    sign = Decimal(1) if open_trade.side == TradeSide.LONG else Decimal(-1)
    open_trade.pnl = sign * (exit_price - open_trade.entry_price) * open_trade.qty
    if open_trade.entry_price > 0:
        open_trade.pnl_pct = sign * (exit_price - open_trade.entry_price) / open_trade.entry_price
    session.flush()
    return open_trade.id


# ── Equity snapshots ───────────────────────────────────────────────────────


def upsert_equity_snapshot(
    session: Session,
    *,
    ts: datetime,
    cash: Decimal,
    equity: Decimal,
    buying_power: Decimal,
    long_exposure: Decimal = Decimal(0),
    short_exposure: Decimal = Decimal(0),
    open_positions: int = 0,
    day_pnl: Decimal = Decimal(0),
    drawdown_pct: Decimal = Decimal(0),
) -> None:
    settings = get_settings()
    mode = (
        BrokerMode.PAPER.value if settings.broker_mode == BrokerMode.PAPER
        else BrokerMode.LIVE.value
    )
    stmt = insert(EquitySnapshot).values(
        ts=ts,
        broker_mode=mode,
        cash=cash,
        equity=equity,
        buying_power=buying_power,
        long_exposure=long_exposure,
        short_exposure=short_exposure,
        open_positions=open_positions,
        day_pnl=day_pnl,
        drawdown_pct=drawdown_pct,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ts", "broker_mode"],
        set_={
            "cash": stmt.excluded.cash,
            "equity": stmt.excluded.equity,
            "buying_power": stmt.excluded.buying_power,
            "long_exposure": stmt.excluded.long_exposure,
            "short_exposure": stmt.excluded.short_exposure,
            "open_positions": stmt.excluded.open_positions,
            "day_pnl": stmt.excluded.day_pnl,
            "drawdown_pct": stmt.excluded.drawdown_pct,
        },
    )
    session.execute(stmt)
