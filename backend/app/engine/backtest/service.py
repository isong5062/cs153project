"""BacktestService: run a walk-forward backtest and persist the result."""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.engine.backtest.walkforward import run_walk_forward
from app.engine.strategies.spec import StrategySpec
from app.models.backtest import Backtest


class BacktestService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def run_and_store(
        self,
        strategy_version_id: int,
        prices: pd.Series,
        features: pd.DataFrame,
        spec: StrategySpec,
        **kwargs,
    ) -> Backtest:
        result = run_walk_forward(prices, features, spec, **kwargs)
        bt = Backtest(
            strategy_version_id=strategy_version_id,
            config={
                "in_sample": kwargs.get("in_sample", 252),
                "out_sample": kwargs.get("out_sample", 126),
                "slippage_bps": kwargs.get("slippage_bps", 5.0),
            },
            result=result.to_dict(),
        )
        self._db.add(bt)
        self._db.commit()
        self._db.refresh(bt)
        return bt
