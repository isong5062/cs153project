"""Order manager (plan §4.7).

Pipeline for a single bar's worth of signals:

    signals → size (risk.sizer) → guard (risk.guards) → broker.submit_order

Invariants:
  - Every submitted order carries a deterministic ``client_order_id`` so a
    retry or duplicate-pipeline call cannot double-fill.
  - Guard rejections are recorded on the outcome with the guard name + reason;
    nothing reaches the broker unless every guard approved.
  - Exits (is_exit=True) bypass sizing and risk guards — closing risk is always
    allowed. Only openings are gated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.broker.base import (
    Account,
    Broker,
    BrokerError,
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from src.risk.guards import (
    GuardDecision,
    GuardVerdict,
    RiskContext,
    TradeProposal,
    evaluate_all,
)
from src.risk.sizer import SizerInput, size_position


@dataclass(slots=True)
class SignalIntent:
    """Input to the order manager. One per symbol per pipeline run."""

    symbol: str
    is_entry: bool
    is_exit: bool
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal | None = None
    strategy_name: str = "unknown"
    # Used to build the idempotent client_order_id; typically a signal UUID.
    origin_id: str | None = None


@dataclass(slots=True)
class OrderOutcome:
    symbol: str
    submitted: bool
    order: Order | None = None
    guard: GuardDecision | None = None
    qty: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


class OrderManager:
    def __init__(
        self,
        broker: Broker,
        *,
        risk_per_trade_pct: float,
        max_position_pct: float,
        max_concurrent_positions: int,
        daily_loss_limit_pct: float,
        max_drawdown_pct: float,
    ) -> None:
        self._broker = broker
        self._risk_per_trade_pct = risk_per_trade_pct
        self._max_position_pct = max_position_pct
        self._max_concurrent_positions = max_concurrent_positions
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._max_drawdown_pct = max_drawdown_pct

    # ── main entry point ───────────────────────────────────────────────────

    def process(
        self,
        intents: list[SignalIntent],
        *,
        peak_equity: Decimal,
        day_start_equity: Decimal,
    ) -> list[OrderOutcome]:
        outcomes: list[OrderOutcome] = []
        account = self._broker.get_account()
        positions = {p.symbol: p.qty for p in self._broker.get_positions()}

        # Close-outs first; frees capital and reduces position count before
        # new-position guards run.
        for intent in [i for i in intents if i.is_exit]:
            outcomes.append(self._handle_exit(intent, positions))

        # Refresh in case exits changed state.
        account = self._broker.get_account()
        positions = {p.symbol: p.qty for p in self._broker.get_positions()}
        day_pnl = account.equity - day_start_equity

        for intent in [i for i in intents if i.is_entry and not i.is_exit]:
            outcome = self._handle_entry(
                intent,
                account_equity=account.equity,
                cash=account.cash,
                buying_power=account.buying_power,
                peak_equity=peak_equity,
                day_start_equity=day_start_equity,
                day_pnl=day_pnl,
                daytrade_count=account.daytrade_count,
                open_positions=positions,
            )
            outcomes.append(outcome)
            # Reflect the new position + buying-power impact so subsequent
            # intents in the same batch see an up-to-date book. Without this,
            # concurrent-position and buying-power caps can be overshot in a
            # single pipeline run.
            if outcome.submitted and outcome.qty > 0:
                positions[intent.symbol] = (
                    positions.get(intent.symbol, Decimal(0)) + Decimal(outcome.qty)
                )
                buying_power_used = Decimal(outcome.qty) * intent.entry_price
                account = _debit_account(account, buying_power_used)
        return outcomes

    # ── entries ────────────────────────────────────────────────────────────

    def _handle_entry(
        self,
        intent: SignalIntent,
        *,
        account_equity: Decimal,
        cash: Decimal,
        buying_power: Decimal,
        peak_equity: Decimal,
        day_start_equity: Decimal,
        day_pnl: Decimal,
        daytrade_count: int,
        open_positions: dict[str, Decimal],
    ) -> OrderOutcome:
        qty = size_position(
            SizerInput(
                equity=account_equity,
                buying_power=buying_power,
                entry_price=intent.entry_price,
                stop_price=intent.stop_price,
                risk_per_trade_pct=self._risk_per_trade_pct,
                max_position_pct=self._max_position_pct,
            )
        )
        if qty <= 0:
            return OrderOutcome(
                symbol=intent.symbol,
                submitted=False,
                qty=0,
                notes=["sizer returned 0 shares"],
            )

        proposal = TradeProposal(
            symbol=intent.symbol,
            qty=qty,
            entry_price=intent.entry_price,
            stop_price=intent.stop_price,
            is_day_trade=False,  # swing horizon; day-trade flag set by execution layer
        )
        ctx = RiskContext(
            equity=account_equity,
            cash=cash,
            buying_power=buying_power,
            peak_equity=peak_equity,
            day_start_equity=day_start_equity,
            day_pnl=day_pnl,
            open_positions=open_positions,
            daytrade_count=daytrade_count,
            max_position_pct=self._max_position_pct,
            max_concurrent_positions=self._max_concurrent_positions,
            daily_loss_limit_pct=self._daily_loss_limit_pct,
            max_drawdown_pct=self._max_drawdown_pct,
        )
        decision = evaluate_all(proposal, ctx)
        if decision.verdict == GuardVerdict.REJECT:
            return OrderOutcome(
                symbol=intent.symbol,
                submitted=False,
                guard=decision,
                qty=qty,
            )

        request = OrderRequest(
            symbol=intent.symbol,
            qty=Decimal(qty),
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            stop_loss=intent.stop_price,
            take_profit=intent.target_price,
            client_order_id=_client_id(intent, "entry"),
        )
        try:
            order = self._broker.submit_order(request)
        except BrokerError as e:
            return OrderOutcome(
                symbol=intent.symbol,
                submitted=False,
                qty=qty,
                guard=decision,
                error=str(e),
            )
        return OrderOutcome(
            symbol=intent.symbol,
            submitted=True,
            order=order,
            qty=qty,
            guard=decision,
        )

    # ── exits ──────────────────────────────────────────────────────────────

    def _handle_exit(
        self, intent: SignalIntent, positions: dict[str, Decimal]
    ) -> OrderOutcome:
        current_qty = positions.get(intent.symbol, Decimal(0))
        if current_qty <= 0:
            return OrderOutcome(
                symbol=intent.symbol,
                submitted=False,
                notes=["no open long to exit"],
            )
        request = OrderRequest(
            symbol=intent.symbol,
            qty=current_qty,
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id=_client_id(intent, "exit"),
        )
        try:
            order = self._broker.submit_order(request)
        except BrokerError as e:
            return OrderOutcome(
                symbol=intent.symbol,
                submitted=False,
                qty=int(current_qty),
                error=str(e),
            )
        return OrderOutcome(
            symbol=intent.symbol, submitted=True, order=order, qty=int(current_qty)
        )


def _debit_account(acct: Account, cost: Decimal) -> Account:
    return Account(
        cash=acct.cash - cost,
        equity=acct.equity,
        buying_power=acct.buying_power - cost,
        daytrade_count=acct.daytrade_count,
        pattern_day_trader=acct.pattern_day_trader,
        extras=acct.extras,
    )


def _client_id(intent: SignalIntent, leg: str) -> str:
    """Deterministic per-intent id so retries collapse to a single order."""
    base = intent.origin_id or f"{intent.strategy_name}:{intent.symbol}"
    # Include a date stamp so the same symbol on different sessions produces
    # distinct client ids (avoids permanent idempotency lock-in).
    day = datetime.now(UTC).strftime("%Y%m%d")
    ns = uuid.NAMESPACE_URL
    return str(uuid.uuid5(ns, f"{day}:{base}:{leg}"))
