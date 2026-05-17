"""Backfill historical bars into Postgres.

Usage:
    uv run python -m scripts.seed_bars                        # default universe, 5yr, daily
    uv run python -m scripts.seed_bars --symbols SPY,QQQ
    uv run python -m scripts.seed_bars --provider yfinance --years 10
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from src.data.cache import ingest
from src.data.providers import AlpacaDataProvider, DataProvider, YFinanceDataProvider
from src.data.universe import DEFAULT_UNIVERSE
from src.logging import configure_logging, get_logger
from src.persistence.models import Timeframe

app = typer.Typer(add_completion=False)
console = Console()


TIMEFRAME_MAP = {
    "1min": Timeframe.MIN_1,
    "5min": Timeframe.MIN_5,
    "15min": Timeframe.MIN_15,
    "hour": Timeframe.HOUR,
    "day": Timeframe.DAY,
}


def _make_provider(kind: str) -> DataProvider:
    if kind == "alpaca":
        return AlpacaDataProvider()
    if kind == "yfinance":
        return YFinanceDataProvider()
    raise typer.BadParameter(f"Unknown provider: {kind}")


@app.command()
def main(
    symbols: str = typer.Option(
        "", help="Comma-separated symbols. Defaults to the full universe."
    ),
    years: int = typer.Option(5, help="How many years of history to pull."),
    timeframe: str = typer.Option("day", help="1min|5min|15min|hour|day"),
    provider: str = typer.Option("alpaca", help="alpaca|yfinance"),
    batch_size: int = typer.Option(
        20, help="Symbols per request (Alpaca supports large batches)."
    ),
) -> None:
    configure_logging()
    log = get_logger("seed_bars")

    tf = TIMEFRAME_MAP[timeframe.lower()]
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # avoid real-time gap
    start = end - timedelta(days=365 * years)

    tickers: list[str] = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else list(DEFAULT_UNIVERSE)
    )

    data_provider = _make_provider(provider)
    console.rule(f"[bold cyan]Seed bars: {provider} / {tf.value} / {years}y")
    console.print(f"Universe: {len(tickers)} symbols\nWindow:   {start.date()} → {end.date()}")

    total_rows = 0
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting", total=len(tickers))
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            try:
                written = ingest(data_provider, batch, start, end, tf)
            except Exception as exc:  # noqa: BLE001 — we want to keep going
                log.error("batch_failed", symbols=batch, error=str(exc))
                progress.advance(task, len(batch))
                continue

            for sym, n in written.items():
                total_rows += n
                if n == 0:
                    log.warning("no_bars", symbol=sym)
            progress.advance(task, len(batch))

    console.rule(f"[bold green]Done: {total_rows:,} bars written")


if __name__ == "__main__":
    app()
