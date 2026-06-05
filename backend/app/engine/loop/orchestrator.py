"""Orchestrator: one trading tick across all active strategies.

For each strategy it computes the regime, evaluates the risk state (with persistent
drawdown blocks), rebalances via the routed executor (live -> Alpaca, rest -> sim),
and records an equity snapshot. Per-strategy errors are isolated so one failure
cannot take down the loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.engine.alerts.service import AlertService
from app.engine.data.market_hours import is_regular_session
from app.engine.execution.router import ExecutionRouter
from app.engine.execution.simulator import SimulatedExecutor
from app.engine.loop.rebalance import rebalance_strategy
from app.engine.risk.manager import RiskManager
from app.engine.strategies.service import StrategyService
from app.models.account import EquitySnapshot
from app.models.regime import Regime
from app.models.strategy import Strategy, StrategyStatus


def _naive_utc(ts) -> datetime:
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.to_pydatetime()


class Orchestrator:
    def __init__(self, db, router=None, risk_manager=None, regime_symbol: str = "SPY") -> None:
        self._db = db
        self._router = router or ExecutionRouter(db, SimulatedExecutor(db))
        self._risk = risk_manager or RiskManager(db)
        self._strategies = StrategyService(db)
        self._regime_symbol = regime_symbol

    def active_strategies(self) -> list[Strategy]:
        return (
            self._db.query(Strategy)
            .filter(Strategy.status.in_([StrategyStatus.live, StrategyStatus.simulated]))
            .all()
        )

    def current_regime(self) -> tuple[str, float, bool]:
        r = (
            self._db.query(Regime)
            .filter_by(symbol=self._regime_symbol)
            .order_by(Regime.ts.desc())
            .first()
        )
        if r is None:
            return "neutral", 0.0, True  # safe default until a model is trained
        return r.label, r.confidence, r.unstable

    def _equity_anchors(
        self, strategy_id: int, now: datetime, equity: float
    ) -> tuple[float, float, float]:
        now_n = _naive_utc(now)
        snaps = (
            self._db.query(EquitySnapshot)
            .filter_by(strategy_id=strategy_id)
            .order_by(EquitySnapshot.ts.asc())
            .all()
        )
        equities = [s.equity for s in snaps] + [equity]
        peak = max(equities)
        today = [s.equity for s in snaps if s.ts.date() == now_n.date()]
        day_start = today[0] if today else equity
        week_ago = now_n - timedelta(days=7)
        week = [s.equity for s in snaps if s.ts >= week_ago]
        week_start = week[0] if week else equity
        return day_start, week_start, peak

    def run_tick(
        self, now: datetime, price_map: dict[str, float], regime=None, force: bool = False
    ) -> dict:
        if not force and not is_regular_session(now):
            return {"status": "skipped_market_closed"}

        label, confidence, unstable = regime if regime is not None else self.current_regime()
        out: dict = {"regime": label, "confidence": confidence, "strategies": {}}

        for strat in self.active_strategies():
            try:
                spec = self._strategies.current_spec(strat)
                if spec is None:
                    continue
                executor = self._router.executor_for(strat)
                equity = executor.equity(strat.id, price_map)
                day_start, week_start, peak = self._equity_anchors(strat.id, now, equity)
                was_blocked = self._risk.is_blocked(strat.id)
                rs = self._risk.evaluate(
                    equity, day_start, week_start, peak, strategy_id=strat.id
                )
                if rs.blocked and not was_blocked:
                    AlertService(self._db).emit(
                        "critical",
                        "circuit_breaker",
                        f"Strategy {strat.id} hit a drawdown stop and is now blocked "
                        "pending manual reset.",
                        {"strategy_id": strat.id, "reasons": rs.reasons, "equity": equity},
                    )
                orders = rebalance_strategy(
                    strat.id, spec, executor, price_map, label, confidence, unstable, rs
                )
                new_equity = executor.equity(strat.id, price_map)
                cash = executor.cash(strat.id) if hasattr(executor, "cash") else None
                self._db.add(
                    EquitySnapshot(
                        strategy_id=strat.id, ts=_naive_utc(now), equity=new_equity, cash=cash
                    )
                )
                self._db.commit()
                out["strategies"][strat.id] = {
                    "orders": len(orders),
                    "halted": rs.halted,
                    "size_mult": rs.size_multiplier,
                }
            except Exception as exc:  # isolate per-strategy failures
                self._db.rollback()
                out["strategies"][strat.id] = {"error": str(exc)}
        return out
