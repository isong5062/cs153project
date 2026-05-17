"""Unit tests for the in-memory SimulatedBroker."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.broker import (
    BrokerError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.broker.simulated import SimulatedBroker


def _buy(symbol="AAPL", qty=10, client_id=None) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        qty=Decimal(qty),
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        client_order_id=client_id,
    )


def test_starting_balance():
    b = SimulatedBroker(starting_cash=50_000)
    acct = b.get_account()
    assert acct.cash == Decimal("50000")
    assert acct.equity == Decimal("50000")


def test_buy_fills_at_mark_and_updates_cash_and_position():
    b = SimulatedBroker(starting_cash=10_000)
    b.set_mark("AAPL", 100)
    order = b.submit_order(_buy(qty=10))
    assert order.status == OrderStatus.FILLED
    assert order.avg_fill_price == Decimal("100")
    acct = b.get_account()
    assert acct.cash == Decimal("9000")
    pos = b.get_position("AAPL")
    assert pos is not None and pos.qty == Decimal("10")


def test_insufficient_cash_raises():
    b = SimulatedBroker(starting_cash=500)
    b.set_mark("AAPL", 100)
    with pytest.raises(BrokerError):
        b.submit_order(_buy(qty=10))


def test_missing_mark_raises():
    b = SimulatedBroker()
    with pytest.raises(BrokerError):
        b.submit_order(_buy())


def test_idempotency_by_client_order_id():
    b = SimulatedBroker(starting_cash=10_000)
    b.set_mark("AAPL", 100)
    first = b.submit_order(_buy(qty=5, client_id="abc"))
    second = b.submit_order(_buy(qty=5, client_id="abc"))
    assert first.id == second.id
    # Cash only decremented once.
    assert b.get_account().cash == Decimal("9500")


def test_sell_closes_position():
    b = SimulatedBroker(starting_cash=10_000)
    b.set_mark("AAPL", 100)
    b.submit_order(_buy(qty=5))
    b.set_mark("AAPL", 110)
    b.submit_order(
        OrderRequest(
            symbol="AAPL",
            qty=Decimal(5),
            side=OrderSide.SELL,
            type=OrderType.MARKET,
        )
    )
    assert b.get_position("AAPL") is None
    assert b.get_account().cash == Decimal("10050")  # +$50 P&L


def test_equity_reflects_unrealized_pnl():
    b = SimulatedBroker(starting_cash=10_000)
    b.set_mark("AAPL", 100)
    b.submit_order(_buy(qty=10))
    b.set_mark("AAPL", 120)
    acct = b.get_account()
    # cash 9000 + market_value 1200 = 10200
    assert acct.equity == Decimal("10200")
