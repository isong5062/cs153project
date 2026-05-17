"""Paper-trading week reporter — the Phase 2 → Phase 3 gate.

Aggregates the past N days of paper-trading state into a single human-readable
report (and an optional JSON dump for archival). Intended to be run on a
Friday after market close once the Phase 2 paper week is complete.

Sections:
  - Window + equity (start/end, return, max drawdown, Sharpe)
  - Per-strategy trade breakdown (count, win rate, P&L)
  - Risk-guard rejections (counts by reason — these MUST be non-zero in tests
    elsewhere, and are informational here)
  - Reconciliation snapshot (current DB vs broker)

Usage:
    uv run python -m scripts.paper_report
    uv run python -m scripts.paper_report --days 7
    uv run python -m scripts.paper_report --json-out report.json
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.broker.alpaca import AlpacaBroker
from src.metrics.live import LiveMetrics, compute_live_metrics
from src.persistence.db import session_scope
from src.persistence.models import Signal, SignalStatus, Strategy, Trade, TradeStatus
from scripts.reconcile import ReconciliationReport, reconcile

app = typer.Typer(add_completion=False)
console = Console()


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:.2f}%" if v is not None else "—"


def _fmt_dec(v: Decimal | None) -> str:
    return f"{v}" if v is not None else "—"


def _print_metrics(m: LiveMetrics) -> None:
    t = Table(title="equity + returns", show_lines=False)
    t.add_column("metric", style="cyan")
    t.add_column("value")
    t.add_row("window", f"{m.window_start} → {m.window_end}")
    t.add_row("snapshots", str(m.n_snapshots))
    t.add_row("starting equity", f"${m.starting_equity}")
    t.add_row("ending equity", f"${m.ending_equity}")
    t.add_row("total return", _fmt_pct(m.total_return_pct))
    t.add_row("max drawdown", _fmt_pct(m.max_drawdown_pct))
    t.add_row(
        "Sharpe (annualized)",
        f"{m.sharpe_annualized:.2f}" if m.sharpe_annualized is not None else "— (need ≥2 returns)",
    )
    t.add_row("closed trades", str(m.n_closed_trades))
    t.add_row("win rate", _fmt_pct(m.win_rate))
    t.add_row("avg win", _fmt_pct(m.avg_win_pct))
    t.add_row("avg loss", _fmt_pct(m.avg_loss_pct))
    t.add_row(
        "profit factor",
        f"{m.profit_factor:.2f}" if m.profit_factor is not None else "—",
    )
    console.print(t)


def _print_per_strategy(rows: list[tuple[str, int, int, Decimal]]) -> None:
    t = Table(title="per-strategy closed trades", show_lines=False)
    t.add_column("strategy", style="cyan")
    t.add_column("trades")
    t.add_column("wins")
    t.add_column("net pnl")
    if not rows:
        console.print("[dim]no closed trades in window[/]")
        return
    for name, n, wins, pnl in rows:
        t.add_row(name, str(n), str(wins), str(pnl))
    console.print(t)


def _print_rejections(counts: Counter[str]) -> None:
    t = Table(title="rejection reasons", show_lines=False)
    t.add_column("reason", style="yellow")
    t.add_column("count")
    if not counts:
        console.print("[dim]no rejected signals in window[/]")
        return
    for reason, n in counts.most_common():
        t.add_row(reason, str(n))
    console.print(t)


def _print_reconciliation(r: ReconciliationReport) -> None:
    t = Table(title="reconciliation (now)", show_lines=False)
    t.add_column("field", style="cyan")
    t.add_column("value")
    t.add_row("db open trades", str(r.db_open_trade_count))
    t.add_row("broker positions", str(r.broker_position_count))
    t.add_row("equity drift", _fmt_dec(r.equity_drift))
    t.add_row("cash drift", _fmt_dec(r.cash_drift))
    t.add_row("position mismatches", str(len(r.position_mismatches)))
    console.print(t)


def _gather_per_strategy(session, start: datetime) -> list[tuple[str, int, int, Decimal]]:
    rows = session.execute(
        select(Trade, Strategy)
        .join(Strategy, Trade.strategy_id == Strategy.id)
        .where(Trade.status == TradeStatus.CLOSED, Trade.exit_ts >= start)
    ).all()
    by_name: dict[str, list[Trade]] = {}
    for trade, strat in rows:
        by_name.setdefault(f"{strat.name}@{strat.version}", []).append(trade)
    out: list[tuple[str, int, int, Decimal]] = []
    for name, trades in sorted(by_name.items()):
        wins = sum(1 for t in trades if (t.pnl or 0) > 0)
        net = sum((t.pnl or Decimal(0) for t in trades), Decimal(0))
        out.append((name, len(trades), wins, net))
    return out


def _gather_rejections(session, start: datetime) -> Counter[str]:
    rejected_statuses = {SignalStatus.REJECTED_BY_RISK, SignalStatus.REJECTED_BY_AGENT}
    rows = session.execute(
        select(Signal.status, Signal.rejection_reason).where(
            Signal.status.in_(rejected_statuses), Signal.ts >= start
        )
    ).all()
    counts: Counter[str] = Counter()
    for status, reason in rows:
        counts[f"{status.value}:{reason or 'unspecified'}"] += 1
    return counts


@app.command()
def main(
    days: int = typer.Option(7, help="Lookback window in days (default: 7)."),
    json_out: Path | None = typer.Option(
        None, help="Also write a JSON dump of the report to this path."
    ),
    skip_reconcile: bool = typer.Option(
        False, help="Skip the live broker reconciliation section."
    ),
) -> None:
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    console.rule(f"[bold cyan]paper-trading report  ({start.date()} → {end.date()})")

    with session_scope() as session:
        metrics = compute_live_metrics(session, broker_mode="paper", start=start, end=end)
        per_strategy = _gather_per_strategy(session, start)
        rejections = _gather_rejections(session, start)

    _print_metrics(metrics)
    _print_per_strategy(per_strategy)
    _print_rejections(rejections)

    recon: ReconciliationReport | None = None
    if not skip_reconcile:
        try:
            recon = reconcile(AlpacaBroker())
            _print_reconciliation(recon)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]reconciliation failed:[/] {type(exc).__name__}: {exc}")

    if json_out is not None:
        payload = {
            "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
            "metrics": _coerce(asdict(metrics)),
            "per_strategy": [
                {"strategy": n, "trades": t, "wins": w, "net_pnl": str(p)}
                for n, t, w, p in per_strategy
            ],
            "rejections": dict(rejections),
            "reconciliation": _coerce(asdict(recon)) if recon is not None else None,
        }
        json_out.write_text(json.dumps(payload, indent=2, default=str))
        console.print(f"[green]wrote[/] {json_out}")


def _coerce(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, list):
        return [_coerce(x) for x in v]
    if isinstance(v, dict):
        return {k: _coerce(x) for k, x in v.items()}
    return v


if __name__ == "__main__":
    app()
