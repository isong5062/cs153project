"""Alpaca broker adapter (paper + live via endpoint config).

Live vs paper is purely a client-construction detail — BROKER_MODE flips the
URL in Settings and the rest of the system is unchanged (plan §4.6, §11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaSide
from alpaca.trading.enums import OrderStatus as AlpacaStatus
from alpaca.trading.enums import OrderType as AlpacaType
from alpaca.trading.enums import TimeInForce as AlpacaTIF
from alpaca.trading.models import TradeAccount
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopLossRequest,
    StopOrderRequest,
    TakeProfitRequest,
)

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
    TimeInForce,
)
from src.config import BrokerMode, get_settings

# ── Enum translation ────────────────────────────────────────────────────────

_SIDE_TO_ALPACA: dict[OrderSide, AlpacaSide] = {
    OrderSide.BUY: AlpacaSide.BUY,
    OrderSide.SELL: AlpacaSide.SELL,
}

_TIF_TO_ALPACA: dict[TimeInForce, AlpacaTIF] = {
    TimeInForce.DAY: AlpacaTIF.DAY,
    TimeInForce.GTC: AlpacaTIF.GTC,
    TimeInForce.OPG: AlpacaTIF.OPG,
    TimeInForce.CLS: AlpacaTIF.CLS,
}

_STATUS_FROM_ALPACA: dict[AlpacaStatus, OrderStatus] = {
    AlpacaStatus.NEW: OrderStatus.NEW,
    AlpacaStatus.ACCEPTED: OrderStatus.ACCEPTED,
    AlpacaStatus.PENDING_NEW: OrderStatus.NEW,
    AlpacaStatus.ACCEPTED_FOR_BIDDING: OrderStatus.ACCEPTED,
    AlpacaStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
    AlpacaStatus.FILLED: OrderStatus.FILLED,
    AlpacaStatus.CANCELED: OrderStatus.CANCELED,
    AlpacaStatus.PENDING_CANCEL: OrderStatus.CANCELED,
    AlpacaStatus.EXPIRED: OrderStatus.EXPIRED,
    AlpacaStatus.REJECTED: OrderStatus.REJECTED,
}

_TYPE_FROM_ALPACA: dict[AlpacaType, OrderType] = {
    AlpacaType.MARKET: OrderType.MARKET,
    AlpacaType.LIMIT: OrderType.LIMIT,
    AlpacaType.STOP: OrderType.STOP,
    AlpacaType.STOP_LIMIT: OrderType.STOP_LIMIT,
}


class AlpacaBroker(Broker):
    """Alpaca paper/live adapter via ``alpaca-py``."""

    name = "alpaca"

    def __init__(self, client: TradingClient | None = None) -> None:
        if client is None:
            settings = get_settings()
            client = TradingClient(
                api_key=settings.alpaca_api_key.get_secret_value(),
                secret_key=settings.alpaca_api_secret.get_secret_value(),
                paper=settings.broker_mode == BrokerMode.PAPER,
            )
        self._client = client

    # ── account / positions ────────────────────────────────────────────────

    def get_account(self) -> Account:
        try:
            raw = self._client.get_account()
        except Exception as e:
            raise BrokerError(f"get_account failed: {e}") from e
        acct = cast(TradeAccount, raw)
        return Account(
            cash=Decimal(str(acct.cash)),
            equity=Decimal(str(acct.equity)),
            buying_power=Decimal(str(acct.buying_power)),
            daytrade_count=int(getattr(acct, "daytrade_count", 0) or 0),
            pattern_day_trader=bool(getattr(acct, "pattern_day_trader", False)),
        )

    def get_positions(self) -> list[Position]:
        try:
            raw = self._client.get_all_positions()
        except Exception as e:
            raise BrokerError(f"get_positions failed: {e}") from e
        return [_pos_from_alpaca(p) for p in raw]

    # ── orders ─────────────────────────────────────────────────────────────

    def submit_order(self, request: OrderRequest) -> Order:
        req = _to_alpaca_request(request)
        try:
            raw = self._client.submit_order(order_data=req)
        except Exception as e:
            raise BrokerError(f"submit_order failed: {e}") from e
        return _order_from_alpaca(raw)

    def cancel_order(self, order_id: str) -> None:
        try:
            self._client.cancel_order_by_id(order_id)
        except Exception as e:
            raise BrokerError(f"cancel_order failed: {e}") from e

    def get_order(self, order_id: str) -> Order:
        try:
            raw = self._client.get_order_by_id(order_id)
        except Exception as e:
            raise BrokerError(f"get_order failed: {e}") from e
        return _order_from_alpaca(raw)

    def list_open_orders(self) -> list[Order]:
        from alpaca.trading.requests import GetOrdersRequest
        try:
            raw = self._client.get_orders(filter=GetOrdersRequest(status="open"))
        except Exception as e:
            raise BrokerError(f"list_open_orders failed: {e}") from e
        return [_order_from_alpaca(o) for o in raw]


# ── translation helpers ─────────────────────────────────────────────────────


def _to_alpaca_request(
    req: OrderRequest,
) -> MarketOrderRequest | LimitOrderRequest | StopOrderRequest | StopLimitOrderRequest:
    side = _SIDE_TO_ALPACA[req.side]
    tif = _TIF_TO_ALPACA[req.time_in_force]
    qty = float(req.qty)

    # Protective legs — Alpaca requires BOTH legs for "bracket"; use "oto" when
    # only one leg is present, and omit order_class entirely when neither is.
    order_class: str | None = None
    take_profit: TakeProfitRequest | None = None
    stop_loss: StopLossRequest | None = None
    has_tp = req.take_profit is not None
    has_sl = req.stop_loss is not None
    if has_tp and has_sl:
        order_class = "bracket"
        take_profit = TakeProfitRequest(limit_price=_tick_round(req.take_profit))  # type: ignore[arg-type]
        stop_loss = StopLossRequest(stop_price=_tick_round(req.stop_loss))  # type: ignore[arg-type]
    elif has_tp or has_sl:
        order_class = "oto"
        if has_tp:
            take_profit = TakeProfitRequest(limit_price=_tick_round(req.take_profit))  # type: ignore[arg-type]
        if has_sl:
            stop_loss = StopLossRequest(stop_price=_tick_round(req.stop_loss))  # type: ignore[arg-type]

    common: dict[str, Any] = dict(
        symbol=req.symbol,
        qty=qty,
        side=side,
        time_in_force=tif,
        client_order_id=req.client_order_id,
        extended_hours=req.extended_hours,
        order_class=order_class,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )
    common = {k: v for k, v in common.items() if v is not None}

    if req.type == OrderType.MARKET:
        return MarketOrderRequest(**common)
    if req.type == OrderType.LIMIT:
        if req.limit_price is None:
            raise BrokerError("limit_price required for LIMIT order")
        return LimitOrderRequest(limit_price=float(req.limit_price), **common)
    if req.type == OrderType.STOP:
        if req.stop_price is None:
            raise BrokerError("stop_price required for STOP order")
        return StopOrderRequest(stop_price=float(req.stop_price), **common)
    if req.type == OrderType.STOP_LIMIT:
        if req.limit_price is None or req.stop_price is None:
            raise BrokerError("limit_price and stop_price required for STOP_LIMIT order")
        return StopLimitOrderRequest(
            limit_price=float(req.limit_price),
            stop_price=float(req.stop_price),
            **common,
        )
    raise BrokerError(f"unsupported order type: {req.type}")


def _order_from_alpaca(o: Any) -> Order:
    return Order(
        id=str(o.id),
        client_order_id=getattr(o, "client_order_id", None),
        symbol=o.symbol,
        qty=Decimal(str(o.qty)),
        filled_qty=Decimal(str(o.filled_qty or 0)),
        side=OrderSide(o.side.value if hasattr(o.side, "value") else str(o.side)),
        type=_TYPE_FROM_ALPACA.get(o.order_type, OrderType.MARKET),
        status=_STATUS_FROM_ALPACA.get(o.status, OrderStatus.NEW),
        limit_price=Decimal(str(o.limit_price)) if o.limit_price else None,
        stop_price=Decimal(str(o.stop_price)) if o.stop_price else None,
        avg_fill_price=Decimal(str(o.filled_avg_price)) if o.filled_avg_price else None,
        submitted_at=_to_utc(o.submitted_at) or datetime.now(UTC),
        filled_at=_to_utc(getattr(o, "filled_at", None)),
    )


def _pos_from_alpaca(p: Any) -> Position:
    qty = Decimal(str(p.qty))
    avg = Decimal(str(p.avg_entry_price))
    price = Decimal(str(p.current_price or p.avg_entry_price))
    return Position(
        symbol=p.symbol,
        qty=qty,
        avg_entry_price=avg,
        market_price=price,
        unrealized_pnl=Decimal(str(p.unrealized_pl or 0)),
    )


def _tick_round(price: Decimal) -> float:
    """Alpaca requires prices ≥$1 in whole cents and <$1 in 1/10000 increments."""
    quant = Decimal("0.01") if price >= 1 else Decimal("0.0001")
    return float(price.quantize(quant, rounding=ROUND_HALF_UP))


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
