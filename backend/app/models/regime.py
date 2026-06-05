"""Regime model + per-bar regime detections."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONVariant


class RegimeModel(Base):
    __tablename__ = "regime_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    n_components: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    params: Mapped[dict] = mapped_column(JSONVariant)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Regime(Base):
    __tablename__ = "regimes"
    __table_args__ = (UniqueConstraint("symbol", "ts", name="uq_regime_symbol_ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    label: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    unstable: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("regime_models.id"))
