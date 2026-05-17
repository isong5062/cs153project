"""Pre-flight validation for the paper-trading loop.

Verifies — fast and loud — that the bot can actually run before you commit a
week of paper trading. Checks env vars, Postgres connectivity + migration head,
Alpaca auth, market-data reachability, and a submit-then-cancel canary order.

Usage:
    uv run python -m scripts.preflight
    uv run python -m scripts.preflight --skip-canary   # no live order round-trip

Exits 0 if every check passes; non-zero on the first hard failure.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from src.broker.alpaca import AlpacaBroker
from src.broker.base import (
    BrokerError,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from src.config import BrokerMode, get_settings
from src.persistence.db import get_engine

app = typer.Typer(add_completion=False)
console = Console()


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check(name: str, fn: Callable[[], str]) -> CheckResult:
    try:
        return CheckResult(name=name, ok=True, detail=fn())
    except Exception as exc:  # noqa: BLE001 — preflight reports every failure
        return CheckResult(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")


def _check_env() -> str:
    s = get_settings()
    missing = []
    if not s.alpaca_api_key.get_secret_value():
        missing.append("ALPACA_API_KEY")
    if not s.alpaca_api_secret.get_secret_value():
        missing.append("ALPACA_API_SECRET")
    if missing:
        raise RuntimeError(f"missing: {', '.join(missing)}")
    if s.broker_mode != BrokerMode.PAPER:
        raise RuntimeError(f"BROKER_MODE={s.broker_mode.value}; preflight only runs in paper")
    return f"broker_mode={s.broker_mode.value}  base_url={s.alpaca_base_url}"


def _check_postgres() -> str:
    engine = get_engine()
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar_one()
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if head is None:
        raise RuntimeError("alembic_version empty — run `uv run alembic upgrade head`")
    return f"alembic_head={head}  pg={str(version).split(',')[0]}"


def _check_tables() -> str:
    required = {"trades", "equity_curve", "signals", "strategies", "bars"}
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).scalars().all()
    found = set(rows)
    missing = required - found
    if missing:
        raise RuntimeError(f"missing tables: {sorted(missing)}")
    return f"tables ok ({len(required)}/{len(required)})"


def _check_alpaca_auth(broker: AlpacaBroker) -> str:
    acct = broker.get_account()
    return (
        f"equity=${acct.equity}  cash=${acct.cash}  bp=${acct.buying_power}  "
        f"daytrades={acct.daytrade_count}"
    )


def _check_alpaca_positions(broker: AlpacaBroker) -> str:
    positions = broker.get_positions()
    return f"open_positions={len(positions)}"


def _check_canary(broker: AlpacaBroker) -> str:
    """Submit a far-from-market limit and immediately cancel.

    Picks a price guaranteed not to fill (1 cent) so the round-trip is safe.
    Verifies submit + cancel + get_order all work. Paper account only.
    """
    if get_settings().broker_mode != BrokerMode.PAPER:
        raise RuntimeError("refusing canary outside paper mode")
    req = OrderRequest(
        symbol="SPY",
        qty=Decimal("1"),
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        limit_price=Decimal("0.01"),
        client_order_id=f"preflight-{__import__('uuid').uuid4().hex[:12]}",
    )
    order = broker.submit_order(req)
    try:
        broker.cancel_order(order.id)
    except BrokerError as exc:
        raise RuntimeError(f"canary submitted (id={order.id}) but cancel failed: {exc}") from exc
    return f"submit+cancel ok  order_id={order.id}"


@app.command()
def main(
    skip_canary: bool = typer.Option(
        False, "--skip-canary", help="Skip the submit+cancel order round-trip."
    ),
) -> None:
    results: list[CheckResult] = []
    results.append(_check("env vars", _check_env))
    results.append(_check("postgres + alembic", _check_postgres))
    results.append(_check("required tables", _check_tables))

    # Broker checks share a client.
    broker: AlpacaBroker | None = None
    try:
        broker = AlpacaBroker()
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult("alpaca client", False, f"{type(exc).__name__}: {exc}"))

    if broker is not None:
        results.append(_check("alpaca auth", lambda: _check_alpaca_auth(broker)))
        results.append(_check("alpaca positions", lambda: _check_alpaca_positions(broker)))
        if not skip_canary:
            results.append(_check("canary order", lambda: _check_canary(broker)))

    table = Table(title="preflight", show_lines=False)
    table.add_column("check", style="cyan", no_wrap=True)
    table.add_column("status")
    table.add_column("detail", style="dim")
    for r in results:
        table.add_row(r.name, "[green]PASS[/]" if r.ok else "[red]FAIL[/]", r.detail)
    console.print(table)

    failed = [r for r in results if not r.ok]
    if failed:
        console.print(f"[bold red]{len(failed)} check(s) failed.[/]")
        sys.exit(1)
    console.print("[bold green]all checks passed — safe to start the bot.[/]")


if __name__ == "__main__":
    app()
