"""Executor protocol shared by the simulated and Alpaca-paper backends."""

from __future__ import annotations

from typing import Protocol

from app.models.execution import Order


class Executor(Protocol):
    name: str

    def submit(
        self, strategy_id: int, symbol: str, side: str, qty: float, price: float | None = None
    ) -> Order: ...

    def positions(self, strategy_id: int) -> dict: ...

    def flatten(self, strategy_id: int, prices: dict | None = None) -> None: ...
