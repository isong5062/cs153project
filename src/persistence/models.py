"""SQLAlchemy 2.0 models.

Schema design notes (see plan §4.8):
- `bars` has a composite PK (symbol, timeframe, ts) and is UPSERT-friendly.
- `signals` persists every signal — accepted AND rejected — because the reflection
  loop needs to learn from what was *not* traded too.
- `agent_runs` stores full prompt/response JSON so replay mode can reconstruct decisions.
- All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    # Bind by .value (e.g. "1Day") instead of member name (e.g. "DAY") so
    # Python values match the Postgres enum's declared labels. create_type=False
    # because the migration owns create/drop of the type.
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        create_type=False,
    )


# ── Enums ───────────────────────────────────────────────────────────────────


class Timeframe(str, enum.Enum):
    MIN_1 = "1Min"
    MIN_5 = "5Min"
    MIN_15 = "15Min"
    HOUR = "1Hour"
    DAY = "1Day"


class SignalAction(str, enum.Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    EXIT = "exit"


class SignalStatus(str, enum.Enum):
    GENERATED = "generated"
    ACCEPTED = "accepted"
    REJECTED_BY_AGENT = "rejected_by_agent"
    REJECTED_BY_RISK = "rejected_by_risk"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"


class TradeSide(str, enum.Enum):
    LONG = "long"
    SHORT = "short"


class TradeStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class BacktestStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReflectionProposalStatus(str, enum.Enum):
    PENDING_BACKTEST = "pending_backtest"
    BACKTESTED_REJECTED = "backtested_rejected"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    LIVE = "live"
    DISCARDED = "discarded"


# ── Market data ─────────────────────────────────────────────────────────────


class Bar(Base):
    """OHLCV bar. Composite PK makes idempotent upserts straightforward."""

    __tablename__ = "bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[Timeframe] = mapped_column(
        _pg_enum(Timeframe, "timeframe_enum"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trade_count: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="alpaca")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    __table_args__ = (Index("ix_bars_ts", "ts"),)


# ── Strategies ──────────────────────────────────────────────────────────────


class Strategy(Base):
    """A registered strategy + parameter set. Multiple versions can coexist."""

    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_champion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    signals: Mapped[list[Signal]] = relationship(back_populates="strategy")
    trades: Mapped[list[Trade]] = relationship(back_populates="strategy")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_strategies_name_version"),
    )


# ── Signals ─────────────────────────────────────────────────────────────────


class Signal(Base):
    """Every signal generated by a strategy, whether or not it became a trade."""

    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    action: Mapped[SignalAction] = mapped_column(
        _pg_enum(SignalAction, "signal_action_enum"), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    entry_price_hint: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    stop_price_hint: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    target_price_hint: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    status: Mapped[SignalStatus] = mapped_column(
        _pg_enum(SignalStatus, "signal_status_enum"),
        nullable=False,
        default=SignalStatus.GENERATED,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # indicator snapshot

    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    strategy: Mapped[Strategy] = relationship(back_populates="signals")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="signal")
    trade: Mapped[Trade | None] = relationship(back_populates="signal", uselist=False)

    __table_args__ = (
        Index("ix_signals_symbol_ts", "symbol", "ts"),
        Index("ix_signals_strategy_ts", "strategy_id", "ts"),
        Index("ix_signals_trace", "trace_id"),
    )


# ── Agent runs ──────────────────────────────────────────────────────────────


class AgentRun(Base):
    """One LLM call. Stored in full so replay mode can reconstruct decisions."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    signal: Mapped[Signal | None] = relationship(back_populates="agent_runs")

    __table_args__ = (
        Index("ix_agent_runs_trace", "trace_id"),
        Index("ix_agent_runs_agent_created", "agent_name", "created_at"),
    )


# ── Trades ──────────────────────────────────────────────────────────────────


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), unique=True
    )

    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[TradeSide] = mapped_column(_pg_enum(TradeSide, "trade_side_enum"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    fees: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    status: Mapped[TradeStatus] = mapped_column(
        _pg_enum(TradeStatus, "trade_status_enum"),
        nullable=False,
        default=TradeStatus.OPEN,
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    client_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)

    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    broker_mode: Mapped[str] = mapped_column(String(8), nullable=False)  # paper | live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    strategy: Mapped[Strategy] = relationship(back_populates="trades")
    signal: Mapped[Signal | None] = relationship(back_populates="trade")

    __table_args__ = (
        Index("ix_trades_symbol_status", "symbol", "status"),
        Index("ix_trades_strategy_status", "strategy_id", "status"),
        Index("ix_trades_entry_ts", "entry_ts"),
    )


# ── Equity curve ────────────────────────────────────────────────────────────


class EquitySnapshot(Base):
    __tablename__ = "equity_curve"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    broker_mode: Mapped[str] = mapped_column(String(8), primary_key=True)

    cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    buying_power: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    long_exposure: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    short_exposure: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    day_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)


# ── Backtests ───────────────────────────────────────────────────────────────


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[BacktestStatus] = mapped_column(
        _pg_enum(BacktestStatus, "backtest_status_enum"),
        nullable=False,
        default=BacktestStatus.QUEUED,
    )

    # Summary stats — populated on completion
    total_return: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sharpe: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    sortino: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    num_trades: Mapped[int | None] = mapped_column(Integer)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # full metrics bag
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_backtests_strategy_status", "strategy_id", "status"),)


# ── Reflection proposals ────────────────────────────────────────────────────


class Reflection(Base):
    """One nightly reflection run's output + its proposals."""

    __tablename__ = "reflections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    summary: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    proposals: Mapped[list[ReflectionProposal]] = relationship(
        back_populates="reflection"
    )


class ReflectionProposal(Base):
    __tablename__ = "reflection_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reflection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reflections.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ReflectionProposalStatus] = mapped_column(
        _pg_enum(ReflectionProposalStatus, "reflection_status_enum"),
        nullable=False,
        default=ReflectionProposalStatus.PENDING_BACKTEST,
    )
    backtest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backtests.id", ondelete="SET NULL")
    )
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    reflection: Mapped[Reflection] = relationship(back_populates="proposals")
