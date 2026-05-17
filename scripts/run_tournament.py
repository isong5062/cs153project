"""Run the Phase-1 tournament over cached bars.

Usage:
    uv run python -m scripts.run_tournament
    uv run python -m scripts.run_tournament --years 3 --symbols SPY,QQQ,AAPL
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console
from rich.table import Table

from src.backtest.data_loader import load_bars
from src.backtest.tournament import run_tournament
from src.backtest.vectorbt_runner import BacktestConfig
from src.data.universe import DEFAULT_UNIVERSE
from src.logging import configure_logging, get_logger
from src.persistence.models import Timeframe
from src.signals.strategies import REGISTRY

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    symbols: str = typer.Option("", help="Comma-separated symbols; empty → default universe."),
    years: int = typer.Option(5, help="History window (years)."),
    train_months: int = typer.Option(12, help="Walk-forward train window."),
    test_months: int = typer.Option(3, help="Walk-forward test window."),
    mc_sims: int = typer.Option(5_000, help="Monte Carlo simulations."),
    fees_bps: float = typer.Option(5.0, help="Per-fill fee in basis points."),
    slippage_bps: float = typer.Option(5.0, help="Slippage in basis points."),
) -> None:
    configure_logging()
    log = get_logger("run_tournament")

    tickers = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else list(DEFAULT_UNIVERSE)
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)

    console.rule(f"[bold cyan]Tournament: {len(tickers)} symbols / {years}y / daily")
    bars = load_bars(tickers, start, end, Timeframe.DAY)
    console.print(f"Loaded bars for {len(bars)}/{len(tickers)} symbols")
    if not bars:
        console.print("[red]No bars found. Run scripts.seed_bars first.")
        raise typer.Exit(code=1)

    cfg = BacktestConfig(fees_bps=fees_bps, slippage_bps=slippage_bps)
    result = run_tournament(
        list(REGISTRY.values()),
        bars,
        train_months=train_months,
        test_months=test_months,
        mc_sims=mc_sims,
        config=cfg,
    )
    log.info("tournament_complete", n_strategies=len(result.entries))

    lb = result.leaderboard()
    table = Table(title="Leaderboard (composite, OOS)")
    for col in lb.columns:
        table.add_column(col)
    for _, row in lb.iterrows():
        table.add_row(*[_fmt(row[c]) for c in lb.columns])
    console.print(table)


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


if __name__ == "__main__":
    app()
