"""Unit tests for the Alpaca request translation layer.

Covers the protective-leg branching: Alpaca rejects ``order_class="bracket"``
unless BOTH take_profit and stop_loss are set, so the adapter must pick
``"oto"`` when only one leg is present.
"""

from __future__ import annotations

from decimal import Decimal

from alpaca.trading.requests import MarketOrderRequest

from src.broker.alpaca import _to_alpaca_request
from src.broker.base import OrderRequest, OrderSide, OrderType, TimeInForce


def _base_request(**overrides: object) -> OrderRequest:
    defaults: dict[str, object] = dict(
        symbol="SPY",
        qty=Decimal("1"),
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="test-id",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)  # type: ignore[arg-type]


def test_no_protective_legs_omits_order_class() -> None:
    req = _to_alpaca_request(_base_request())
    assert isinstance(req, MarketOrderRequest)
    assert req.order_class is None
    assert req.take_profit is None
    assert req.stop_loss is None


def test_stop_only_uses_oto() -> None:
    req = _to_alpaca_request(_base_request(stop_loss=Decimal("400")))
    assert req.order_class == "oto"
    assert req.stop_loss is not None
    assert req.take_profit is None


def test_target_only_uses_oto() -> None:
    req = _to_alpaca_request(_base_request(take_profit=Decimal("500")))
    assert req.order_class == "oto"
    assert req.take_profit is not None
    assert req.stop_loss is None


def test_both_legs_use_bracket() -> None:
    req = _to_alpaca_request(
        _base_request(stop_loss=Decimal("400"), take_profit=Decimal("500"))
    )
    assert req.order_class == "bracket"
    assert req.take_profit is not None
    assert req.stop_loss is not None


def test_protective_legs_rounded_to_cents() -> None:
    req = _to_alpaca_request(
        _base_request(
            stop_loss=Decimal("316.2645"),
            take_profit=Decimal("420.7891"),
        )
    )
    assert req.stop_loss.stop_price == 316.26
    assert req.take_profit.limit_price == 420.79


def test_sub_dollar_price_uses_four_decimals() -> None:
    req = _to_alpaca_request(_base_request(stop_loss=Decimal("0.123456")))
    assert req.stop_loss.stop_price == 0.1235
