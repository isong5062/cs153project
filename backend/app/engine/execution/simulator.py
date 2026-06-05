"""SimulatedExecutor: internal paper-fill engine with a virtual wallet.

Long-only in v1. Fills at the provided reference price (e.g. the next bar's open)
plus/minus slippage. Used for every strategy except the single live one.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.execution import Fill, Order, OrderSide, OrderStatus, Position, SimWallet


class SimulatedExecutor:
    name = "sim"

    def __init__(
        self, db: Session, slippage_bps: float = 5.0, initial_cash: float = 100_000.0
    ) -> None:
        self._db = db
        self._slip = slippage_bps / 1e4
        self._initial = initial_cash

    def _wallet(self, strategy_id: int) -> SimWallet:
        w = self._db.get(SimWallet, strategy_id)
        if w is None:
            w = SimWallet(strategy_id=strategy_id, cash=self._initial, initial_cash=self._initial)
            self._db.add(w)
            self._db.flush()
        return w

    def _position(self, strategy_id: int, symbol: str) -> Position:
        p = (
            self._db.query(Position)
            .filter_by(strategy_id=strategy_id, symbol=symbol, executor="sim")
            .one_or_none()
        )
        if p is None:
            p = Position(
                strategy_id=strategy_id, symbol=symbol, qty=0.0, avg_price=0.0, executor="sim"
            )
            self._db.add(p)
            self._db.flush()
        return p

    def submit(self, strategy_id, symbol, side, qty, price=None) -> Order:
        if price is None:
            raise ValueError("SimulatedExecutor requires a reference price")
        side = OrderSide(side)
        fill_price = price * (1 + self._slip) if side == OrderSide.buy else price * (1 - self._slip)

        wallet = self._wallet(strategy_id)
        pos = self._position(strategy_id, symbol)
        if side == OrderSide.buy:
            new_qty = pos.qty + qty
            pos.avg_price = (
                (pos.avg_price * pos.qty + fill_price * qty) / new_qty if new_qty else 0.0
            )
            pos.qty = new_qty
            wallet.cash -= fill_price * qty
        else:
            pos.qty -= qty
            wallet.cash += fill_price * qty
            if pos.qty == 0:
                pos.avg_price = 0.0

        order = Order(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            qty=qty,
            status=OrderStatus.filled,
            executor="sim",
        )
        self._db.add(order)
        self._db.flush()
        self._db.add(
            Fill(
                order_id=order.id,
                strategy_id=strategy_id,
                symbol=symbol,
                qty=qty,
                price=fill_price,
            )
        )
        self._db.commit()
        self._db.refresh(order)
        return order

    def positions(self, strategy_id: int) -> dict[str, Position]:
        rows = self._db.query(Position).filter_by(strategy_id=strategy_id, executor="sim").all()
        return {p.symbol: p for p in rows if p.qty != 0}

    def flatten(self, strategy_id: int, prices: dict | None = None) -> None:
        prices = prices or {}
        for sym, p in list(self.positions(strategy_id).items()):
            ref = prices.get(sym, p.avg_price)
            if p.qty > 0:
                self.submit(strategy_id, sym, "sell", p.qty, ref)
            elif p.qty < 0:
                self.submit(strategy_id, sym, "buy", -p.qty, ref)

    def equity(self, strategy_id: int, prices: dict) -> float:
        wallet = self._wallet(strategy_id)
        mtm = sum(
            p.qty * prices.get(sym, p.avg_price)
            for sym, p in self.positions(strategy_id).items()
        )
        return wallet.cash + mtm

    def cash(self, strategy_id: int) -> float:
        return self._wallet(strategy_id).cash
