"""Strategy CRUD, versioning, promotion, status, performance, trades."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import (
    CreateStrategyRequest,
    SetStatusRequest,
    StrategyOut,
    UpdateSpecRequest,
    VersionOut,
)
from app.db.session import get_db
from app.engine.execution.router import ExecutionRouter
from app.engine.execution.simulator import SimulatedExecutor
from app.engine.performance.metrics import summarize
from app.engine.strategies.service import StrategyService
from app.models.account import EquitySnapshot
from app.models.execution import Order
from app.models.strategy import Strategy
from app.models.user import User

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _owned(db: Session, user: User, strategy_id: int) -> Strategy:
    s = db.get(Strategy, strategy_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "strategy not found")
    return s


@router.get("", response_model=list[StrategyOut])
def list_strategies(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.query(Strategy).filter_by(user_id=user.id).order_by(Strategy.id).all()


@router.post("", response_model=StrategyOut, status_code=201)
def create_strategy(
    body: CreateStrategyRequest, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return StrategyService(db).create_strategy(user.id, body.name, body.spec)


@router.get("/{strategy_id}", response_model=StrategyOut)
def get_strategy(
    strategy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return _owned(db, user, strategy_id)


@router.get("/{strategy_id}/spec")
def get_spec(
    strategy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    s = _owned(db, user, strategy_id)
    spec = StrategyService(db).current_spec(s)
    if spec is None:
        raise HTTPException(404, "no current spec")
    return spec.model_dump(mode="json")


@router.put("/{strategy_id}/spec", response_model=VersionOut)
def update_spec(
    strategy_id: int,
    body: UpdateSpecRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned(db, user, strategy_id)
    return StrategyService(db).update_spec(strategy_id, body.spec)


@router.get("/{strategy_id}/versions", response_model=list[VersionOut])
def versions(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, user, strategy_id)
    return StrategyService(db).list_versions(strategy_id)


@router.post("/{strategy_id}/promote", response_model=StrategyOut)
def promote(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = _owned(db, user, strategy_id)
    ExecutionRouter(db, SimulatedExecutor(db)).promote(strategy_id)
    db.refresh(s)
    return s


@router.post("/{strategy_id}/status", response_model=StrategyOut)
def set_status(
    strategy_id: int,
    body: SetStatusRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    s = _owned(db, user, strategy_id)
    s.status = body.status
    db.commit()
    db.refresh(s)
    return s


@router.get("/{strategy_id}/performance")
def performance(
    strategy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    _owned(db, user, strategy_id)
    snaps = (
        db.query(EquitySnapshot)
        .filter_by(strategy_id=strategy_id)
        .order_by(EquitySnapshot.ts.asc())
        .all()
    )
    equity = [{"ts": s.ts.isoformat(), "equity": s.equity} for s in snaps]
    rets = (
        pd.Series([s.equity for s in snaps]).pct_change().dropna()
        if len(snaps) > 1
        else pd.Series(dtype=float)
    )
    return {"equity_curve": equity, "metrics": summarize(rets)}


@router.get("/{strategy_id}/trades")
def trades(
    strategy_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned(db, user, strategy_id)
    orders = (
        db.query(Order)
        .filter_by(strategy_id=strategy_id)
        .order_by(Order.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": o.id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": o.qty,
            "status": o.status,
            "executor": o.executor,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]
