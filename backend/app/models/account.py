"""Per-strategy equity snapshots (for risk anchors, performance, dashboard)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
