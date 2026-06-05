"""Risk status + manual circuit-breaker reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.engine.risk.manager import RiskManager
from app.models.risk import RiskEvent

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/status")
def status(strategy_id: int | None = None, db: Session = Depends(get_db)):
    rm = RiskManager(db)
    events = db.query(RiskEvent).order_by(RiskEvent.id.desc()).limit(20).all()
    return {
        "blocked": rm.is_blocked(strategy_id),
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "scope": e.scope,
                "strategy_id": e.strategy_id,
                "resolved": e.resolved,
                "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            }
            for e in events
        ],
    }


@router.post("/reset/{event_id}")
def reset(event_id: int, db: Session = Depends(get_db)):
    if not RiskManager(db).reset_block(event_id):
        raise HTTPException(400, "could not reset (not found or already resolved)")
    return {"reset": True}
