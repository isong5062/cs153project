"""Rule-based risk guards (plan §4.5).

Pure functions. Each guard takes the proposal + account context and returns a
``GuardDecision``. ``evaluate_all`` runs the full pipeline; an APPROVE means
every guard passed.

Property invariants (tested with hypothesis):
  - No input can make ``evaluate_all`` approve a trade that breaches the
    configured max-position-pct, max-concurrent-positions, daily-loss, or
    max-drawdown limit.
  - PDT guard rejects trades that would open a 4th day-trade within 5 days
    while equity < $25,000.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal


class GuardVerdict(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(slots=True)
class GuardDecision:
    verdict: GuardVerdict
    guard: str
    reason: str = ""

    @classmethod
    def approve(cls, guard: str) -> GuardDecision:
        return cls(GuardVerdict.APPROVE, guard)

    @classmethod
    def reject(cls, guard: str, reason: str) -> GuardDecision:
        return cls(GuardVerdict.REJECT, guard, reason)


@dataclass(slots=True)
class TradeProposal:
    symbol: str
    qty: int
    entry_price: Decimal
    stop_price: Decimal
    is_day_trade: bool = False  # True if entry+exit would happen same session


@dataclass(slots=True)
class RiskContext:
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    peak_equity: Decimal            # running high-water mark
    day_start_equity: Decimal       # equity at session open
    day_pnl: Decimal                # realized + unrealized since session open
    open_positions: dict[str, Decimal] = field(default_factory=dict)  # symbol -> qty (signed)
    # Alpaca PDT fields
    daytrade_count: int = 0          # trades in rolling 5-session window
    pattern_day_trader: bool = False

    # Limits (mirror Settings)
    max_position_pct: float = 0.05
    max_concurrent_positions: int = 10
    daily_loss_limit_pct: float = 0.02
    max_drawdown_pct: float = 0.08
    pdt_equity_threshold: Decimal = Decimal("25000")


PDT_DAYTRADE_LIMIT = 3  # Alpaca's rolling-5-day cap


def check_drawdown(ctx: RiskContext) -> GuardDecision:
    if ctx.peak_equity <= 0:
        return GuardDecision.approve("drawdown")
    dd = (ctx.peak_equity - ctx.equity) / ctx.peak_equity
    if dd >= Decimal(str(ctx.max_drawdown_pct)):
        return GuardDecision.reject(
            "drawdown",
            f"drawdown {dd:.2%} exceeds max {ctx.max_drawdown_pct:.2%}",
        )
    return GuardDecision.approve("drawdown")


def check_daily_loss(ctx: RiskContext) -> GuardDecision:
    if ctx.day_start_equity <= 0:
        return GuardDecision.approve("daily_loss")
    loss_pct = -ctx.day_pnl / ctx.day_start_equity if ctx.day_pnl < 0 else Decimal("0")
    if loss_pct >= Decimal(str(ctx.daily_loss_limit_pct)):
        return GuardDecision.reject(
            "daily_loss",
            f"day loss {loss_pct:.2%} exceeds limit {ctx.daily_loss_limit_pct:.2%}",
        )
    return GuardDecision.approve("daily_loss")


def check_position_cap(p: TradeProposal, ctx: RiskContext) -> GuardDecision:
    if p.qty <= 0:
        return GuardDecision.reject("position_cap", "qty <= 0")
    notional = Decimal(p.qty) * p.entry_price
    cap = Decimal(str(ctx.max_position_pct)) * ctx.equity
    if notional > cap:
        return GuardDecision.reject(
            "position_cap",
            f"notional {notional} > cap {cap}",
        )
    return GuardDecision.approve("position_cap")


def check_concurrent_positions(p: TradeProposal, ctx: RiskContext) -> GuardDecision:
    # Opening a new symbol counts; increasing an existing position does not.
    opens_new = p.symbol not in ctx.open_positions
    if opens_new and len(ctx.open_positions) >= ctx.max_concurrent_positions:
        return GuardDecision.reject(
            "concurrent_positions",
            f"would exceed {ctx.max_concurrent_positions} open positions",
        )
    return GuardDecision.approve("concurrent_positions")


def check_buying_power(p: TradeProposal, ctx: RiskContext) -> GuardDecision:
    needed = Decimal(p.qty) * p.entry_price
    if needed > ctx.buying_power:
        return GuardDecision.reject(
            "buying_power",
            f"need {needed}, have {ctx.buying_power}",
        )
    return GuardDecision.approve("buying_power")


def check_pdt(p: TradeProposal, ctx: RiskContext) -> GuardDecision:
    # PDT only bites sub-$25K accounts. If the proposal is a day-trade and this
    # one would be the 4th within the rolling 5-session window, block it.
    if ctx.equity >= ctx.pdt_equity_threshold:
        return GuardDecision.approve("pdt")
    if not p.is_day_trade:
        return GuardDecision.approve("pdt")
    if ctx.daytrade_count >= PDT_DAYTRADE_LIMIT:
        return GuardDecision.reject(
            "pdt",
            f"would be day-trade #{ctx.daytrade_count + 1} on <$25K account",
        )
    return GuardDecision.approve("pdt")


ALL_GUARDS = (
    ("drawdown", lambda p, c: check_drawdown(c)),
    ("daily_loss", lambda p, c: check_daily_loss(c)),
    ("concurrent_positions", check_concurrent_positions),
    ("position_cap", check_position_cap),
    ("buying_power", check_buying_power),
    ("pdt", check_pdt),
)


def evaluate_all(proposal: TradeProposal, ctx: RiskContext) -> GuardDecision:
    """Run all guards; first rejection wins. Returns approve from a sentinel
    guard name ``"all"`` on success so callers have a uniform result shape."""
    for _name, fn in ALL_GUARDS:
        decision = fn(proposal, ctx)
        if decision.verdict == GuardVerdict.REJECT:
            return decision
    return GuardDecision.approve("all")
