"""ExecutionRouter: exactly one strategy is "live" (Alpaca paper); the rest are
simulated. Promotion flattens the outgoing live strategy and rebinds the new one.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.execution.base import Executor
from app.models.strategy import Strategy, StrategyStatus


class ExecutionRouter:
    def __init__(self, db: Session, sim: Executor, alpaca: Executor | None = None) -> None:
        self._db = db
        self._sim = sim
        self._alpaca = alpaca

    def executor_for(self, strategy: Strategy) -> Executor:
        if strategy.status == StrategyStatus.live and self._alpaca is not None:
            return self._alpaca
        return self._sim

    def live_strategy(self) -> Strategy | None:
        return self._db.query(Strategy).filter_by(status=StrategyStatus.live).first()

    def promote(self, strategy_id: int, flatten_prices: dict | None = None) -> None:
        current = self.live_strategy()
        if current is not None and current.id != strategy_id:
            if self._alpaca is not None:
                self._alpaca.flatten(current.id)
            else:
                self._sim.flatten(current.id, flatten_prices or {})
            current.status = StrategyStatus.simulated

        strat = self._db.get(Strategy, strategy_id)
        if strat is None:
            raise ValueError("strategy not found")
        strat.status = StrategyStatus.live
        self._db.commit()
