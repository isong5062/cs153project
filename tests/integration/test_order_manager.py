"""End-to-end: signal intent → sizer → guards → SimulatedBroker.

This is the Phase 2 milestone check — the trading loop places paper trades
with only rule-based strategies and the risk guards have demonstrable veto
power.
"""

from __future__ import annotations

from decimal import Decimal

from src.broker.simulated import SimulatedBroker
from src.execution.order_manager import OrderManager, SignalIntent


def _om(broker: SimulatedBroker) -> OrderManager:
    return OrderManager(
        broker=broker,
        risk_per_trade_pct=0.01,
        max_position_pct=0.05,
        max_concurrent_positions=10,
        daily_loss_limit_pct=0.02,
        max_drawdown_pct=0.08,
    )


def test_happy_path_opens_and_closes_position():
    broker = SimulatedBroker(starting_cash=100_000)
    broker.set_mark("AAPL", 100)
    om = _om(broker)

    entry = SignalIntent(
        symbol="AAPL",
        is_entry=True,
        is_exit=False,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        origin_id="sig-1",
    )
    outcomes = om.process(
        [entry],
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )
    assert len(outcomes) == 1
    assert outcomes[0].submitted is True
    assert outcomes[0].qty > 0
    assert broker.get_position("AAPL") is not None

    # Now exit.
    exit_ = SignalIntent(
        symbol="AAPL",
        is_entry=False,
        is_exit=True,
        entry_price=Decimal("100"),
        stop_price=Decimal("0"),
        origin_id="sig-1",
    )
    outcomes = om.process(
        [exit_],
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )
    assert outcomes[0].submitted is True
    assert broker.get_position("AAPL") is None


def test_drawdown_guard_vetoes_new_entry():
    broker = SimulatedBroker(starting_cash=90_000)  # "down" vs peak
    broker.set_mark("AAPL", 100)
    om = _om(broker)

    entry = SignalIntent(
        symbol="AAPL",
        is_entry=True,
        is_exit=False,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        origin_id="sig-dd",
    )
    outcomes = om.process(
        [entry],
        peak_equity=Decimal("100000"),     # -10% from peak, limit 8%
        day_start_equity=Decimal("100000"),
    )
    assert outcomes[0].submitted is False
    assert outcomes[0].guard is not None
    assert outcomes[0].guard.guard == "drawdown"
    assert broker.get_position("AAPL") is None


def test_idempotent_on_retry():
    broker = SimulatedBroker(starting_cash=100_000)
    broker.set_mark("AAPL", 100)
    om = _om(broker)

    intent = SignalIntent(
        symbol="AAPL",
        is_entry=True,
        is_exit=False,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        origin_id="sig-idem",
        strategy_name="mean_reversion",
    )
    first = om.process([intent], peak_equity=Decimal("100000"),
                       day_start_equity=Decimal("100000"))
    second = om.process([intent], peak_equity=Decimal("100000"),
                        day_start_equity=Decimal("100000"))
    assert first[0].order is not None and second[0].order is not None
    assert first[0].order.id == second[0].order.id
    # Position only opened once.
    pos = broker.get_position("AAPL")
    assert pos is not None
    assert pos.qty == Decimal(first[0].qty)


def test_exit_without_position_is_no_op():
    broker = SimulatedBroker(starting_cash=100_000)
    broker.set_mark("AAPL", 100)
    om = _om(broker)
    exit_ = SignalIntent(
        symbol="AAPL", is_entry=False, is_exit=True,
        entry_price=Decimal("100"), stop_price=Decimal("0"),
    )
    outcomes = om.process(
        [exit_], peak_equity=Decimal("100000"), day_start_equity=Decimal("100000")
    )
    assert outcomes[0].submitted is False


def test_concurrent_positions_cap_rejects_eleventh():
    broker = SimulatedBroker(starting_cash=1_000_000)
    symbols = [f"SYM{i}" for i in range(11)]
    for s in symbols:
        broker.set_mark(s, 50)
    om = _om(broker)
    intents = [
        SignalIntent(symbol=s, is_entry=True, is_exit=False,
                     entry_price=Decimal("50"), stop_price=Decimal("47"),
                     origin_id=f"sig-{s}")
        for s in symbols
    ]
    outcomes = om.process(
        intents, peak_equity=Decimal("1000000"), day_start_equity=Decimal("1000000")
    )
    submitted = [o for o in outcomes if o.submitted]
    rejected = [o for o in outcomes if not o.submitted]
    assert len(submitted) == 10
    assert len(rejected) == 1
    assert rejected[0].guard is not None
    assert rejected[0].guard.guard == "concurrent_positions"
