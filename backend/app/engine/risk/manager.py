"""RiskManager: combines circuit-breaker math with persistent drawdown blocks.

A drawdown stop writes an unresolved RiskEvent that keeps the account/strategy
halted until a human explicitly resets it (the video's "block file" pattern).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.engine.risk.limits import GLOBAL_LIMITS, RiskLimits, RiskState, evaluate_breakers
from app.models.risk import RiskEvent, RiskScope


class RiskManager:
    def __init__(self, db: Session, limits: RiskLimits = GLOBAL_LIMITS) -> None:
        self._db = db
        self._limits = limits

    def active_block(self, strategy_id: int | None = None) -> RiskEvent | None:
        q = self._db.query(RiskEvent).filter(
            RiskEvent.event_type == "drawdown_stop", RiskEvent.resolved.is_(False)
        )
        if strategy_id is not None:
            q = q.filter(RiskEvent.strategy_id == strategy_id)
        else:
            q = q.filter(RiskEvent.scope == RiskScope.account)
        return q.first()

    def is_blocked(self, strategy_id: int | None = None) -> bool:
        return self.active_block(strategy_id) is not None

    def record_event(
        self,
        event_type: str,
        action: str,
        scope: RiskScope = RiskScope.account,
        strategy_id: int | None = None,
        detail: dict | None = None,
    ) -> RiskEvent:
        ev = RiskEvent(
            scope=scope,
            strategy_id=strategy_id,
            event_type=event_type,
            action=action,
            detail=detail or {},
        )
        self._db.add(ev)
        self._db.commit()
        self._db.refresh(ev)
        return ev

    def evaluate(
        self,
        equity: float,
        day_start: float,
        week_start: float,
        peak: float,
        strategy_id: int | None = None,
    ) -> RiskState:
        state = evaluate_breakers(equity, day_start, week_start, peak, self._limits)
        scope = RiskScope.strategy if strategy_id is not None else RiskScope.account

        if state.blocked and self.active_block(strategy_id) is None:
            self.record_event(
                "drawdown_stop", "halt+block", scope, strategy_id, {"equity": equity, "peak": peak}
            )

        # An existing unresolved block forces a halt regardless of current equity.
        if self.is_blocked(strategy_id):
            state.halted = True
            state.blocked = True
            state.size_multiplier = 0.0
            if "drawdown_stop" not in state.reasons:
                state.reasons.append("active_block")
        return state

    def reset_block(self, event_id: int) -> bool:
        ev = self._db.get(RiskEvent, event_id)
        if ev is None or ev.resolved:
            return False
        ev.resolved = True
        ev.resolved_at = datetime.now(UTC)
        self._db.commit()
        return True
