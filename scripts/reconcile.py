"""Reconcile DB state against Alpaca paper account.

Catches the silent-divergence failure mode: DB thinks a trade is open but
Alpaca closed it (stop hit on the broker side), or DB has a position size that
no longer matches the broker. Phase 3 layers LLMs on top of this loop — if the
ground truth drifts, agents will reason from a fiction.

Compares:
  - open trades (DB ``trades`` rows with status='open') vs Alpaca positions
    (symbol + signed qty)
  - DB cash/equity (latest ``equity_curve`` row) vs Alpaca account snapshot

Usage:
    uv run python -m scripts.reconcile
    uv run python -m scripts.reconcile --json   # machine-readable for cron
    uv run python -m scripts.reconcile --strict # exit 1 on any mismatch
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.broker.alpaca import AlpacaBroker
from src.broker.base import Position
from src.persistence.db import session_scope
from src.persistence.models import EquitySnapshot, Trade, TradeSide, TradeStatus

app = typer.Typer(add_completion=False)
console = Console()

# Tolerances — equity drifts intra-bar via mark-to-market, so allow a small
# absolute window before flagging. Position qty must match exactly (whole shares).
EQUITY_TOLERANCE_USD = Decimal("1.00")
CASH_TOLERANCE_USD = Decimal("1.00")


@dataclass(slots=True)
class PositionMismatch:
    symbol: str
    db_qty: Decimal | None
    broker_qty: Decimal | None
    kind: str  # "missing_in_broker" | "missing_in_db" | "qty_mismatch"


@dataclass(slots=True)
class ReconciliationReport:
    ts: str
    db_open_trade_count: int
    broker_position_count: int
    position_mismatches: list[PositionMismatch] = field(default_factory=list)
    equity_db: Decimal | None = None
    equity_broker: Decimal | None = None
    cash_db: Decimal | None = None
    cash_broker: Decimal | None = None
    equity_drift: Decimal | None = None
    cash_drift: Decimal | None = None

    @property
    def has_drift(self) -> bool:
        if self.position_mismatches:
            return True
        if self.equity_drift is not None and abs(self.equity_drift) > EQUITY_TOLERANCE_USD:
            return True
        if self.cash_drift is not None and abs(self.cash_drift) > CASH_TOLERANCE_USD:
            return True
        return False


def _signed_qty(t: Trade) -> Decimal:
    return t.qty if t.side == TradeSide.LONG else -t.qty


def _signed_broker_qty(p: Position) -> Decimal:
    return p.qty  # already signed in our Position dataclass


def _reconcile_positions(
    db_open: list[Trade], broker_positions: list[Position]
) -> list[PositionMismatch]:
    db_by_symbol: dict[str, Decimal] = {}
    for t in db_open:
        db_by_symbol[t.symbol] = db_by_symbol.get(t.symbol, Decimal(0)) + _signed_qty(t)
    broker_by_symbol = {p.symbol: _signed_broker_qty(p) for p in broker_positions}

    mismatches: list[PositionMismatch] = []
    for sym, db_qty in db_by_symbol.items():
        broker_qty = broker_by_symbol.get(sym)
        if broker_qty is None:
            mismatches.append(PositionMismatch(sym, db_qty, None, "missing_in_broker"))
        elif db_qty != broker_qty:
            mismatches.append(PositionMismatch(sym, db_qty, broker_qty, "qty_mismatch"))
    for sym, broker_qty in broker_by_symbol.items():
        if sym not in db_by_symbol:
            mismatches.append(PositionMismatch(sym, None, broker_qty, "missing_in_db"))
    return mismatches


def reconcile(broker: AlpacaBroker) -> ReconciliationReport:
    acct = broker.get_account()
    broker_positions = broker.get_positions()

    with session_scope() as session:
        open_trades = list(
            session.execute(select(Trade).where(Trade.status == TradeStatus.OPEN)).scalars()
        )
        latest_equity = session.execute(
            select(EquitySnapshot).order_by(EquitySnapshot.ts.desc()).limit(1)
        ).scalar_one_or_none()

    mismatches = _reconcile_positions(open_trades, broker_positions)
    report = ReconciliationReport(
        ts=datetime.now(UTC).isoformat(),
        db_open_trade_count=len(open_trades),
        broker_position_count=len(broker_positions),
        position_mismatches=mismatches,
        equity_broker=acct.equity,
        cash_broker=acct.cash,
    )
    if latest_equity is not None:
        report.equity_db = latest_equity.equity
        report.cash_db = latest_equity.cash
        report.equity_drift = acct.equity - latest_equity.equity
        report.cash_drift = acct.cash - latest_equity.cash
    return report


def _print_report(report: ReconciliationReport) -> None:
    summary = Table(title="reconciliation summary", show_lines=False)
    summary.add_column("field", style="cyan")
    summary.add_column("value")
    summary.add_row("timestamp", report.ts)
    summary.add_row("db open trades", str(report.db_open_trade_count))
    summary.add_row("broker positions", str(report.broker_position_count))
    summary.add_row("equity (db / broker)", f"{report.equity_db} / {report.equity_broker}")
    summary.add_row(
        "equity drift",
        f"{report.equity_drift}" if report.equity_drift is not None else "(no db row)",
    )
    summary.add_row("cash (db / broker)", f"{report.cash_db} / {report.cash_broker}")
    summary.add_row(
        "cash drift", f"{report.cash_drift}" if report.cash_drift is not None else "(no db row)"
    )
    console.print(summary)

    if report.position_mismatches:
        mm = Table(title="position mismatches", show_lines=False)
        mm.add_column("symbol", style="cyan")
        mm.add_column("kind", style="yellow")
        mm.add_column("db_qty")
        mm.add_column("broker_qty")
        for m in report.position_mismatches:
            mm.add_row(m.symbol, m.kind, str(m.db_qty), str(m.broker_qty))
        console.print(mm)
    else:
        console.print("[green]no position mismatches[/]")


@app.command()
def main(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON to stdout instead of tables."),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any drift is detected."),
) -> None:
    broker = AlpacaBroker()
    report = reconcile(broker)

    if json_out:
        payload = asdict(report)
        # Decimals -> strings for JSON
        def _coerce(v):
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, list):
                return [_coerce(x) for x in v]
            if isinstance(v, dict):
                return {k: _coerce(x) for k, x in v.items()}
            return v
        print(json.dumps(_coerce(payload), indent=2))
    else:
        _print_report(report)

    if strict and report.has_drift:
        sys.exit(1)


if __name__ == "__main__":
    app()
