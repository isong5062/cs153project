"""Entry point: start the paper-trading loop.

Wires:
  AlpacaBroker (paper) ← config.BROKER_MODE flips paper/live
  OrderManager        ← reads risk limits from Settings
  SignalProducer      ← runs Phase-1 strategies on cached bars
  Persistence repos   ← writes signals, trades, equity to Postgres
  TradingScheduler    ← APScheduler cron jobs (US/Eastern)

Usage:
    uv run python -m scripts.run_paper_bot
    uv run python -m scripts.run_paper_bot --once   # run one signal cycle and exit
    uv run python -m scripts.run_paper_bot --symbols SPY,QQQ --strategy trend_following

Pre-reqs:
  - .env with ALPACA_API_KEY / ALPACA_API_SECRET (paper keys)
  - Postgres reachable at POSTGRES_URL with migrations applied
  - Bars seeded for the universe (`uv run python -m scripts.seed_bars`)
"""

from __future__ import annotations

import signal as os_signal
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import typer
from rich.console import Console

from src.broker.alpaca import AlpacaBroker
from src.config import BrokerMode, get_settings
from src.data.universe import DEFAULT_UNIVERSE
from src.execution.order_manager import OrderManager, OrderOutcome, SignalIntent
from src.execution.signal_producer import ProducerConfig, SignalProducer
from src.logging import configure_logging, get_logger
from src.persistence.db import session_scope
from src.persistence.repos import (
    close_trade,
    record_signal,
    record_trade_open,
    upsert_equity_snapshot,
    upsert_strategies,
)
from src.scheduler.jobs import build_scheduler
from src.signals.strategies import REGISTRY, all_default

app = typer.Typer(add_completion=False)
console = Console()


def _build_strategies(names: list[str] | None):
    if not names:
        return all_default()
    chosen = []
    for n in names:
        if n not in REGISTRY:
            raise typer.BadParameter(f"unknown strategy {n}; have {sorted(REGISTRY)}")
        chosen.append(REGISTRY[n](params={}))
    return chosen


def _make_outcome_recorder(strategy_ids: dict[str, uuid.UUID]):
    """Return a closure suitable for `record_outcomes` on TradingScheduler."""

    def record(intents: list[SignalIntent], outcomes: list[OrderOutcome]) -> None:
        # Pair intents to outcomes by symbol (order manager keeps order).
        by_symbol_intent: dict[str, SignalIntent] = {i.symbol: i for i in intents}
        with session_scope() as session:
            for outcome in outcomes:
                intent = by_symbol_intent.get(outcome.symbol)
                if intent is None:
                    continue
                strategy_id = strategy_ids.get(intent.strategy_name)
                if strategy_id is None:
                    # Producer used a strategy we didn't register — skip.
                    continue
                trace_id = uuid.uuid4()
                signal_id = record_signal(
                    session,
                    intent=intent,
                    outcome=outcome,
                    strategy_id=strategy_id,
                    trace_id=trace_id,
                )
                if outcome.submitted and outcome.order is not None:
                    if intent.is_exit:
                        close_trade(
                            session,
                            symbol=intent.symbol,
                            exit_price=outcome.order.avg_fill_price or intent.entry_price,
                            exit_ts=outcome.order.filled_at or datetime.now(UTC),
                        )
                    elif intent.is_entry:
                        record_trade_open(
                            session,
                            intent=intent,
                            outcome=outcome,
                            strategy_id=strategy_id,
                            signal_id=signal_id,
                            trace_id=trace_id,
                        )

    return record


def _make_equity_recorder(broker: AlpacaBroker):
    def record(equity: Decimal, day_pnl: Decimal) -> None:
        positions = broker.get_positions()
        long_exp = sum((p.market_value for p in positions if p.is_long), Decimal(0))
        short_exp = sum((-p.market_value for p in positions if not p.is_long), Decimal(0))
        with session_scope() as session:
            upsert_equity_snapshot(
                session,
                ts=datetime.now(UTC),
                cash=broker.get_account().cash,
                equity=equity,
                buying_power=broker.get_account().buying_power,
                long_exposure=long_exp,
                short_exposure=short_exp,
                open_positions=len(positions),
                day_pnl=day_pnl,
            )
    return record


@app.command()
def main(
    once: bool = typer.Option(False, help="Run a single generate-and-submit cycle, then exit."),
    symbols: str = typer.Option("", help="Comma-separated symbols. Defaults to DEFAULT_UNIVERSE."),
    strategy: list[str] = typer.Option(  # noqa: B008
        None, help="Strategy name(s) to run; repeatable. Defaults to all registered."
    ),
    stop_pct: float = typer.Option(0.05, help="Stop-loss as fraction below entry."),
    target_pct: float | None = typer.Option(None, help="Take-profit as fraction above entry."),
    lookback_days: int = typer.Option(200, help="Bar history pulled per symbol."),
    timezone: str = typer.Option("US/Eastern", help="Scheduler timezone."),
) -> None:
    configure_logging()
    log = get_logger("paper_bot")

    settings = get_settings()
    if settings.broker_mode != BrokerMode.PAPER:
        console.print(
            f"[bold red]REFUSING TO START[/]: BROKER_MODE={settings.broker_mode.value}. "
            "Phase-2 entrypoint only runs in paper. Phase 7 covers the live flip."
        )
        raise typer.Exit(code=2)

    broker = AlpacaBroker()
    acct = broker.get_account()
    console.rule("[bold cyan]paper bot starting")
    console.print(
        f"broker=alpaca paper  equity=${acct.equity}  cash=${acct.cash}  bp=${acct.buying_power}"
    )

    universe = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else list(DEFAULT_UNIVERSE)
    )
    strategies = _build_strategies(list(strategy) if strategy else None)
    console.print(
        f"universe={len(universe)} symbols  strategies={[s.name for s in strategies]}"
    )

    # Register strategies so signal/trade FKs resolve.
    with session_scope() as session:
        strategy_ids_raw = upsert_strategies(session, strategies)
    # Producer tags intents as ``f"{name}@{version}"`` — match that key here.
    strategy_ids = {f"{s.name}@{s.version}": strategy_ids_raw[f"{s.name}@{s.version}"]
                    for s in strategies}

    om = OrderManager(
        broker=broker,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        max_position_pct=settings.max_position_pct,
        max_concurrent_positions=settings.max_concurrent_positions,
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        max_drawdown_pct=settings.max_drawdown_pct,
    )
    producer = SignalProducer(
        ProducerConfig(
            universe=universe,
            strategies=strategies,
            lookback_days=lookback_days,
            stop_pct=stop_pct,
            target_pct=target_pct,
        )
    )
    record_outcomes = _make_outcome_recorder(strategy_ids)
    record_equity = _make_equity_recorder(broker)

    sched = build_scheduler(
        broker,
        om,
        producer,
        record_equity=record_equity,
        record_outcomes=record_outcomes,
        timezone=timezone,
    )

    if once:
        log.info("paper_bot.once.start")
        sched.pre_market()
        sched.generate_and_submit()
        sched.manage_intraday()
        log.info("paper_bot.once.done")
        return

    # Long-running: start scheduler, wait for SIGINT.
    sched.start()
    console.print("[bold green]scheduler running. Ctrl-C to stop.[/]")

    stop = False
    def _handle_sigint(_signum, _frame):
        nonlocal stop
        stop = True
    os_signal.signal(os_signal.SIGINT, _handle_sigint)
    if hasattr(os_signal, "SIGTERM"):
        os_signal.signal(os_signal.SIGTERM, _handle_sigint)

    try:
        while not stop:
            time.sleep(1)
    finally:
        console.print("[yellow]shutting down…[/]")
        sched.shutdown(wait=True)
        sys.exit(0)


if __name__ == "__main__":
    app()
