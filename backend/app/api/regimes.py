"""Regime endpoints: current + history."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import RegimeOut
from app.db.session import get_db
from app.models.regime import Regime

router = APIRouter(prefix="/regimes", tags=["regimes"])


@router.get("/current", response_model=RegimeOut | None)
def current(symbol: str = "SPY", db: Session = Depends(get_db)):
    return (
        db.query(Regime).filter_by(symbol=symbol).order_by(Regime.ts.desc()).first()
    )


@router.get("/history", response_model=list[RegimeOut])
def history(symbol: str = "SPY", limit: int = 200, db: Session = Depends(get_db)):
    rows = (
        db.query(Regime)
        .filter_by(symbol=symbol)
        .order_by(Regime.ts.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))
