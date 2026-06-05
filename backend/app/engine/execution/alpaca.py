"""AlpacaExecutor: submits PAPER orders for the single live strategy.

The trading client is injectable so the round-trip can be unit-tested without a
network connection. Construction asserts the paper-only lock.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.paper_lock import assert_paper_only
from app.models.execution import Order, OrderSide, OrderStatus


class AlpacaExecutor:
    name = "alpaca"

    def __init__(self, settings, db: Session, client=None) -> None:
        assert_paper_only(settings)
        self._db = db
        self._client = client or self._make_client(settings)

    @staticmethod
    def _make_client(settings):
        from alpaca.trading.client import TradingClient

        return TradingClient(settings.alpaca_api_key, settings.alpaca_secret_key, paper=True)

    def submit(self, strategy_id, symbol, side, qty, price=None) -> Order:
        from alpaca.trading.enums import OrderSide as ASide
        from alpaca.trading.enums import TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=ASide.BUY if side == "buy" else ASide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        broker_order = self._client.submit_order(req)
        order = Order(
            strategy_id=strategy_id,
            symbol=symbol,
            side=OrderSide(side),
            qty=qty,
            status=OrderStatus.submitted,
            executor="alpaca",
            broker_order_id=str(getattr(broker_order, "id", "")),
        )
        self._db.add(order)
        self._db.commit()
        self._db.refresh(order)
        return order

    def positions(self, strategy_id: int) -> dict:
        return {p.symbol: p for p in self._client.get_all_positions()}

    def flatten(self, strategy_id: int, prices: dict | None = None) -> None:
        self._client.close_all_positions(cancel_orders=True)

    def account(self):
        return self._client.get_account()

    def equity(self, strategy_id: int, price_map=None) -> float:
        return float(self.account().equity)

    def cash(self, strategy_id: int) -> float:
        return float(self.account().cash)
