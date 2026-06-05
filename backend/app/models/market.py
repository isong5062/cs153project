"""Market data models: OHLCV bars and engineered feature rows.

All timestamps are stored as naive UTC for cross-DB portability (SQLite/Postgres).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONVariant


class Bar(Base):
    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_bar_symbol_tf_ts"),
        Index("ix_bars_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(8))  # "1Day" | "5Min" | "1Min"
    ts: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class FeatureRow(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_feature_symbol_tf_ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(8))
    ts: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    values: Mapped[dict] = mapped_column(JSONVariant)
