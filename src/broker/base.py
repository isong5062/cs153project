"""Broker interface.

One shape, three backends (plan §4.6):
  - AlpacaBroker  — paper/live, same class, endpoint from config
  - SimulatedBroker — in-memory, used by tests and the order-manager integration

Going live is a config flip (BROKER_MODE=live); code is identical. The
dataclasses here are the neutral vocabulary the rest of the system speaks;
adapter modules translate to/from their SDK's native types.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, enum.Enum):
    DAY = "day"
    GTC = "gtc"
    OPG = "opg"  # market-on-open
    CLS = "cls"  # market-on-close


class OrderStatus(str, enum.Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class BrokerError(RuntimeError):
    """Raised for any broker-side failure. Callers should treat as non-fatal."""


@dataclass(slots=True)
class OrderRequest:
    """Neutral order request. ``client_order_id`` MUST be unique per intent —
    duplicates are how the order manager stays idempotent across retries."""

    symbol: str
    qty: Decimal
    side: OrderSide
    type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    # Bracket legs — optional; brokers that don't support them natively
    # can be layered in the order manager (see Phase 2 §4.7).
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    client_order_id: str | None = None
    extended_hours: bool = False


@dataclass(slots=True)
class Order:
    id: str
    client_order_id: str | None
    symbol: str
    qty: Decimal
    filled_qty: Decimal
    side: OrderSide
    type: OrderType
    status: OrderStatus
    limit_price: Decimal | None
    stop_price: Decimal | None
    avg_fill_price: Decimal | None
    submitted_at: datetime
    filled_at: datetime | None = None


@dataclass(slots=True)
class Position:
    symbol: str
    qty: Decimal  # signed: +long, -short
    avg_entry_price: Decimal
    market_price: Decimal
    unrealized_pnl: Decimal

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    @property
    def market_value(self) -> Decimal:
        return self.qty * self.market_price


@dataclass(slots=True)
class Account:
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    # Alpaca tracks this directly; used by the PDT guard.
    daytrade_count: int = 0
    pattern_day_trader: bool = False
    extras: dict[str, object] = field(default_factory=dict)


class Broker(ABC):
    """Minimal broker surface the trading loop depends on."""

    name: str = "base"

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    def get_position(self, symbol: str) -> Position | None:
        return next((p for p in self.get_positions() if p.symbol == symbol), None)

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def list_open_orders(self) -> list[Order]: ...
