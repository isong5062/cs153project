"""Operational alerts feed (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.alert import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(limit: int = 50, level: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Alert)
    if level is not None:
        q = q.filter(Alert.level == level)
    rows = q.order_by(Alert.id.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "level": a.level,
            "category": a.category,
            "message": a.message,
            "detail": a.detail,
            "delivered": a.delivered,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]
