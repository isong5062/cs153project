"""Unit + property tests for the rule-based risk guards."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from src.risk.guards import (
    PDT_DAYTRADE_LIMIT,
    GuardVerdict,
    RiskContext,
    TradeProposal,
    check_concurrent_positions,
    check_daily_loss,
    check_drawdown,
    check_pdt,
    check_position_cap,
    evaluate_all,
)


def _ctx(**kw) -> RiskContext:
    defaults = dict(
        equity=Decimal("100000"),
        cash=Decimal("50000"),
        buying_power=Decimal("100000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        day_pnl=Decimal("0"),
        open_positions={},
        daytrade_count=0,
        pattern_day_trader=False,
    )
    defaults.update(kw)
    return RiskContext(**defaults)


def _proposal(**kw) -> TradeProposal:
    defaults = dict(
        symbol="AAPL",
        qty=10,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        is_day_trade=False,
    )
    defaults.update(kw)
    return TradeProposal(**defaults)


# ── Individual guards ──────────────────────────────────────────────────────


def test_drawdown_trips_at_threshold():
    ctx = _ctx(peak_equity=Decimal("100000"), equity=Decimal("91000"),
               max_drawdown_pct=0.08)
    assert check_drawdown(ctx).verdict == GuardVerdict.REJECT


def test_drawdown_ok_when_below_threshold():
    ctx = _ctx(peak_equity=Decimal("100000"), equity=Decimal("95000"),
               max_drawdown_pct=0.08)
    assert check_drawdown(ctx).verdict == GuardVerdict.APPROVE


def test_daily_loss_trips():
    ctx = _ctx(day_start_equity=Decimal("100000"), day_pnl=Decimal("-2500"),
               daily_loss_limit_pct=0.02)
    assert check_daily_loss(ctx).verdict == GuardVerdict.REJECT


def test_daily_loss_ignores_gains():
    ctx = _ctx(day_pnl=Decimal("5000"), daily_loss_limit_pct=0.02)
    assert check_daily_loss(ctx).verdict == GuardVerdict.APPROVE


def test_position_cap_rejects_oversized():
    # 5% of 100k = 5000; 100 shares @ $100 = 10000.
    p = _proposal(qty=100, entry_price=Decimal("100"))
    ctx = _ctx(max_position_pct=0.05)
    assert check_position_cap(p, ctx).verdict == GuardVerdict.REJECT


def test_concurrent_positions_blocks_new_when_full():
    ctx = _ctx(
        open_positions={f"SYM{i}": Decimal("1") for i in range(10)},
        max_concurrent_positions=10,
    )
    assert check_concurrent_positions(_proposal(symbol="NEW"), ctx).verdict == GuardVerdict.REJECT


def test_concurrent_positions_allows_adding_to_existing():
    ctx = _ctx(
        open_positions={f"SYM{i}": Decimal("1") for i in range(10)} | {"AAPL": Decimal("1")},
        max_concurrent_positions=10,
    )
    # symbol AAPL already in book, not opening new
    assert check_concurrent_positions(_proposal(symbol="AAPL"), ctx).verdict == GuardVerdict.APPROVE


def test_pdt_blocks_4th_daytrade_sub_25k():
    ctx = _ctx(equity=Decimal("20000"), daytrade_count=PDT_DAYTRADE_LIMIT)
    assert check_pdt(_proposal(is_day_trade=True), ctx).verdict == GuardVerdict.REJECT


def test_pdt_allows_above_25k():
    ctx = _ctx(equity=Decimal("30000"), daytrade_count=10)
    assert check_pdt(_proposal(is_day_trade=True), ctx).verdict == GuardVerdict.APPROVE


def test_pdt_allows_swing_trades():
    ctx = _ctx(equity=Decimal("20000"), daytrade_count=10)
    assert check_pdt(_proposal(is_day_trade=False), ctx).verdict == GuardVerdict.APPROVE


# ── Integrated evaluate_all ────────────────────────────────────────────────


def test_evaluate_all_approves_happy_path():
    assert evaluate_all(_proposal(), _ctx()).verdict == GuardVerdict.APPROVE


# ── Property invariants ────────────────────────────────────────────────────


@given(
    equity=st.decimals(min_value=Decimal("1000"), max_value=Decimal("1000000"),
                       allow_nan=False, allow_infinity=False, places=2),
    qty=st.integers(min_value=1, max_value=100000),
    entry=st.decimals(min_value=Decimal("1"), max_value=Decimal("1000"),
                      allow_nan=False, allow_infinity=False, places=2),
    stop_gap=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("50"),
                         allow_nan=False, allow_infinity=False, places=2),
    max_pos_pct=st.floats(min_value=0.001, max_value=0.5),
)
def test_approve_implies_position_within_cap(equity, qty, entry, stop_gap, max_pos_pct):
    assume(stop_gap < entry)
    ctx = _ctx(
        equity=equity, buying_power=equity, cash=equity,
        peak_equity=equity, day_start_equity=equity,
        max_position_pct=max_pos_pct,
    )
    p = _proposal(qty=qty, entry_price=entry, stop_price=entry - stop_gap)
    result = evaluate_all(p, ctx)
    if result.verdict == GuardVerdict.APPROVE:
        notional = Decimal(qty) * entry
        assert notional <= Decimal(str(max_pos_pct)) * equity


@given(
    dd_pct=st.floats(min_value=0.0, max_value=0.5),
    limit_pct=st.floats(min_value=0.01, max_value=0.3),
)
def test_approve_implies_drawdown_within_limit(dd_pct, limit_pct):
    peak = Decimal("100000")
    equity = peak * (Decimal("1") - Decimal(str(dd_pct)))
    ctx = _ctx(
        peak_equity=peak, equity=equity,
        day_start_equity=equity,
        buying_power=equity, cash=equity,
        max_drawdown_pct=limit_pct,
        max_position_pct=0.5,   # keep position-cap permissive
    )
    result = evaluate_all(_proposal(qty=1, entry_price=Decimal("1"), stop_price=Decimal("0.5")), ctx)
    if result.verdict == GuardVerdict.APPROVE:
        realised_dd = (peak - equity) / peak
        assert realised_dd < Decimal(str(limit_pct))


@given(
    day_pnl=st.decimals(min_value=Decimal("-10000"), max_value=Decimal("10000"),
                        allow_nan=False, allow_infinity=False, places=2),
    limit_pct=st.floats(min_value=0.005, max_value=0.2),
)
def test_approve_implies_daily_loss_within_limit(day_pnl, limit_pct):
    start = Decimal("100000")
    equity = start + day_pnl
    assume(equity > 0)
    ctx = _ctx(
        equity=equity,
        peak_equity=max(equity, start),
        day_start_equity=start,
        day_pnl=day_pnl,
        buying_power=equity, cash=equity,
        daily_loss_limit_pct=limit_pct,
        max_position_pct=0.5,
    )
    result = evaluate_all(_proposal(qty=1, entry_price=Decimal("1"), stop_price=Decimal("0.5")), ctx)
    if result.verdict == GuardVerdict.APPROVE and day_pnl < 0:
        assert (-day_pnl / start) < Decimal(str(limit_pct))
