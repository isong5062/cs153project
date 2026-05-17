"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-14

Creates all Phase 0+ tables: bars, strategies, signals, agent_runs, trades,
equity_curve, backtests, reflections, reflection_proposals, plus the enum types.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum definitions reused across create/drop.
# create_type=False disables auto-create-on-table-create; we create/drop
# the types explicitly in upgrade()/downgrade(). Must use postgresql.ENUM
# (not sa.Enum) because create_type is a Postgres-specific flag.
_TIMEFRAME = postgresql.ENUM(
    "1Min", "5Min", "15Min", "1Hour", "1Day",
    name="timeframe_enum", create_type=False,
)
_SIGNAL_ACTION = postgresql.ENUM(
    "long", "short", "flat", "exit",
    name="signal_action_enum", create_type=False,
)
_SIGNAL_STATUS = postgresql.ENUM(
    "generated",
    "accepted",
    "rejected_by_agent",
    "rejected_by_risk",
    "executed",
    "execution_failed",
    name="signal_status_enum",
    create_type=False,
)
_TRADE_SIDE = postgresql.ENUM(
    "long", "short", name="trade_side_enum", create_type=False,
)
_TRADE_STATUS = postgresql.ENUM(
    "open", "closed", "cancelled", name="trade_status_enum", create_type=False,
)
_BACKTEST_STATUS = postgresql.ENUM(
    "queued", "running", "completed", "failed",
    name="backtest_status_enum", create_type=False,
)
_REFLECTION_STATUS = postgresql.ENUM(
    "pending_backtest",
    "backtested_rejected",
    "pending_approval",
    "approved",
    "live",
    "discarded",
    name="reflection_status_enum",
    create_type=False,
)


def upgrade() -> None:
    # Create enums up front so other tables can reference them
    bind = op.get_bind()
    for enum in (
        _TIMEFRAME,
        _SIGNAL_ACTION,
        _SIGNAL_STATUS,
        _TRADE_SIDE,
        _TRADE_STATUS,
        _BACKTEST_STATUS,
        _REFLECTION_STATUS,
    ):
        enum.create(bind, checkfirst=True)

    # ── bars ──
    op.create_table(
        "bars",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("timeframe", _TIMEFRAME, primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.Column("trade_count", sa.BigInteger),
        sa.Column("vwap", sa.Numeric(18, 6)),
        sa.Column("source", sa.String(32), nullable=False, server_default="alpaca"),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_bars_ts", "bars", ["ts"])

    # ── strategies ──
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "is_champion", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("name", "version", name="uq_strategies_name_version"),
    )

    # ── signals ──
    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", _SIGNAL_ACTION, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("entry_price_hint", sa.Numeric(18, 6)),
        sa.Column("stop_price_hint", sa.Numeric(18, 6)),
        sa.Column("target_price_hint", sa.Numeric(18, 6)),
        sa.Column(
            "status", _SIGNAL_STATUS, nullable=False, server_default="generated"
        ),
        sa.Column("rejection_reason", sa.Text),
        sa.Column("features", postgresql.JSONB),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_signals_symbol_ts", "signals", ["symbol", "ts"])
    op.create_index("ix_signals_strategy_ts", "signals", ["strategy_id", "ts"])
    op.create_index("ix_signals_trace", "signals", ["trace_id"])

    # ── agent_runs ──
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signals.id", ondelete="SET NULL"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("input_payload", postgresql.JSONB, nullable=False),
        sa.Column("output_payload", postgresql.JSONB),
        sa.Column("raw_response", postgresql.JSONB),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_runs_trace", "agent_runs", ["trace_id"])
    op.create_index(
        "ix_agent_runs_agent_created", "agent_runs", ["agent_name", "created_at"]
    )

    # ── trades ──
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signals.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("side", _TRADE_SIDE, nullable=False),
        sa.Column("qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 6)),
        sa.Column("target_price", sa.Numeric(18, 6)),
        sa.Column("exit_ts", sa.DateTime(timezone=True)),
        sa.Column("exit_price", sa.Numeric(18, 6)),
        sa.Column("fees", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("pnl", sa.Numeric(18, 6)),
        sa.Column("pnl_pct", sa.Numeric(10, 6)),
        sa.Column("status", _TRADE_STATUS, nullable=False, server_default="open"),
        sa.Column("broker_order_id", sa.String(64)),
        sa.Column("client_order_id", sa.String(64), unique=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("broker_mode", sa.String(8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_trades_symbol_status", "trades", ["symbol", "status"])
    op.create_index("ix_trades_strategy_status", "trades", ["strategy_id", "status"])
    op.create_index("ix_trades_entry_ts", "trades", ["entry_ts"])

    # ── equity_curve ──
    op.create_table(
        "equity_curve",
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("broker_mode", sa.String(8), primary_key=True),
        sa.Column("cash", sa.Numeric(18, 4), nullable=False),
        sa.Column("equity", sa.Numeric(18, 4), nullable=False),
        sa.Column("buying_power", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "long_exposure", sa.Numeric(18, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "short_exposure", sa.Numeric(18, 4), nullable=False, server_default="0"
        ),
        sa.Column("open_positions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("day_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column(
            "drawdown_pct", sa.Numeric(10, 6), nullable=False, server_default="0"
        ),
    )

    # ── backtests ──
    op.create_table(
        "backtests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe", postgresql.JSONB, nullable=False),
        sa.Column(
            "config", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", _BACKTEST_STATUS, nullable=False, server_default="queued"),
        sa.Column("total_return", sa.Numeric(10, 6)),
        sa.Column("sharpe", sa.Numeric(10, 4)),
        sa.Column("sortino", sa.Numeric(10, 4)),
        sa.Column("max_drawdown", sa.Numeric(10, 6)),
        sa.Column("win_rate", sa.Numeric(5, 4)),
        sa.Column("num_trades", sa.Integer),
        sa.Column("turnover", sa.Numeric(10, 4)),
        sa.Column("stats", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_backtests_strategy_status", "backtests", ["strategy_id", "status"]
    )

    # ── reflections ──
    op.create_table(
        "reflections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("findings", postgresql.JSONB),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "reflection_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reflection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reflections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "target_strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="SET NULL"),
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("rationale", sa.Text),
        sa.Column(
            "status",
            _REFLECTION_STATUS,
            nullable=False,
            server_default="pending_backtest",
        ),
        sa.Column(
            "backtest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backtests.id", ondelete="SET NULL"),
        ),
        sa.Column("approved_by", sa.String(64)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("reflection_proposals")
    op.drop_table("reflections")
    op.drop_index("ix_backtests_strategy_status", table_name="backtests")
    op.drop_table("backtests")
    op.drop_table("equity_curve")
    op.drop_index("ix_trades_entry_ts", table_name="trades")
    op.drop_index("ix_trades_strategy_status", table_name="trades")
    op.drop_index("ix_trades_symbol_status", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_agent_runs_agent_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_trace", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_signals_trace", table_name="signals")
    op.drop_index("ix_signals_strategy_ts", table_name="signals")
    op.drop_index("ix_signals_symbol_ts", table_name="signals")
    op.drop_table("signals")
    op.drop_table("strategies")
    op.drop_index("ix_bars_ts", table_name="bars")
    op.drop_table("bars")

    bind = op.get_bind()
    for enum in (
        _REFLECTION_STATUS,
        _BACKTEST_STATUS,
        _TRADE_STATUS,
        _TRADE_SIDE,
        _SIGNAL_STATUS,
        _SIGNAL_ACTION,
        _TIMEFRAME,
    ):
        enum.drop(bind, checkfirst=True)
