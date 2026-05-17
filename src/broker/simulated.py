"""In-memory broker for tests and the order-manager integration.

Not a backtest engine — that's vectorbt's job (plan §8). This exists so:
  1. The scheduler + order-manager path can be exercised without hitting Alpaca.
  2. Risk-guard integration tests have deterministic account/position state.

Fills happen immediately at the last supplied ``mark_price`` (or the order's
limit, for limit orders). There is no order book, no partial fills, no slippage
model — anything more sophisticated belongs in the vectorbt tier.
"""

from __future__ import annotations

import itertools
import threading
from datetime import UTC, datetime
from decimal import Decimal

from src.broker.base import (
    Account,
    Broker,
    BrokerError,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class SimulatedBroker(Broker):
    """Deterministic in-memory broker."""

    name = "simulated"

    def __init__(self, starting_cash: Decimal | float = Decimal("100000")) -> None:
        self._cash = Decimal(str(starting_cash))
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._client_ids_seen: dict[str, str] = {}  # client_order_id -> order_id
        self._marks: dict[str, Decimal] = {}
        self._id_seq = itertools.count(1)
        self._lock = threading.Lock()

    # ── test helpers ────────────────────────────────────────────────────────

    def set_mark(self, symbol: str, price: Decimal | float) -> None:
        self._marks[symbol] = Decimal(str(price))
        pos = self._positions.get(symbol)
        if pos:
            self._positions[symbol] = Position(
                symbol=pos.symbol,
                qty=pos.qty,
                avg_entry_price=pos.avg_entry_price,
                market_price=Decimal(str(price)),
                unrealized_pnl=(Decimal(str(price)) - pos.avg_entry_price) * pos.qty,
            )

    # ── Broker interface ────────────────────────────────────────────────────

    def get_account(self) -> Account:
        equity = self._cash + sum(
            (p.market_value for p in self._positions.values()), Decimal("0")
        )
        return Account(
            cash=self._cash,
            equity=equity,
            buying_power=self._cash,  # cash account, no margin
            daytrade_count=0,
            pattern_day_trader=False,
        )

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def submit_order(self, request: OrderRequest) -> Order:
        with self._lock:
            if request.client_order_id and request.client_order_id in self._client_ids_seen:
                # Idempotent: same client id returns the existing order.
                return self._orders[self._client_ids_seen[request.client_order_id]]

            fill_price = self._resolve_fill_price(request)
            if fill_price is None:
                raise BrokerError(
                    f"no mark price for {request.symbol}; call set_mark() first"
                )

            qty = Decimal(str(request.qty))
            if qty <= 0:
                raise BrokerError("qty must be positive")

            signed = qty if request.side == OrderSide.BUY else -qty
            cost = signed * fill_price
            if request.side == OrderSide.BUY and cost > self._cash:
                raise BrokerError(
                    f"insufficient cash: need {cost}, have {self._cash}"
                )

            self._apply_fill(request.symbol, signed, fill_price)
            self._cash -= cost

            oid = f"sim-{next(self._id_seq)}"
            now = datetime.now(UTC)
            order = Order(
                id=oid,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                qty=qty,
                filled_qty=qty,
                side=request.side,
                type=request.type,
                status=OrderStatus.FILLED,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                avg_fill_price=fill_price,
                submitted_at=now,
                filled_at=now,
            )
            self._orders[oid] = order
            if request.client_order_id:
                self._client_ids_seen[request.client_order_id] = oid
            return order

    def cancel_order(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if order is None:
            raise BrokerError(f"unknown order {order_id}")
        # Sim fills immediately, so cancel is a no-op unless someone stubs
        # the broker to keep orders open.
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED):
            return
        self._orders[order_id] = _with_status(order, OrderStatus.CANCELED)

    def get_order(self, order_id: str) -> Order:
        if order_id not in self._orders:
            raise BrokerError(f"unknown order {order_id}")
        return self._orders[order_id]

    def list_open_orders(self) -> list[Order]:
        return [
            o
            for o in self._orders.values()
            if o.status in (OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED)
        ]

    # ── internals ───────────────────────────────────────────────────────────

    def _resolve_fill_price(self, req: OrderRequest) -> Decimal | None:
        if req.type == OrderType.MARKET:
            return self._marks.get(req.symbol)
        if req.type == OrderType.LIMIT and req.limit_price is not None:
            return req.limit_price
        return self._marks.get(req.symbol)

    def _apply_fill(self, symbol: str, signed_qty: Decimal, price: Decimal) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            if signed_qty == 0:
                return
            self._positions[symbol] = Position(
                symbol=symbol,
                qty=signed_qty,
                avg_entry_price=price,
                market_price=price,
                unrealized_pnl=Decimal("0"),
            )
            return

        new_qty = pos.qty + signed_qty
        if new_qty == 0:
            del self._positions[symbol]
            return
        # Only update avg when adding in the same direction.
        same_direction = (pos.qty > 0 and signed_qty > 0) or (
            pos.qty < 0 and signed_qty < 0
        )
        if same_direction:
            notional = pos.avg_entry_price * pos.qty + price * signed_qty
            avg = notional / new_qty
        else:
            avg = pos.avg_entry_price
        self._positions[symbol] = Position(
            symbol=symbol,
            qty=new_qty,
            avg_entry_price=avg,
            market_price=price,
            unrealized_pnl=(price - avg) * new_qty,
        )


def _with_status(o: Order, status: OrderStatus) -> Order:
    return Order(
        id=o.id,
        client_order_id=o.client_order_id,
        symbol=o.symbol,
        qty=o.qty,
        filled_qty=o.filled_qty,
        side=o.side,
        type=o.type,
        status=status,
        limit_price=o.limit_price,
        stop_price=o.stop_price,
        avg_fill_price=o.avg_fill_price,
        submitted_at=o.submitted_at,
        filled_at=o.filled_at,
    )
