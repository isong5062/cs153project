"""Strategy + immutable version models."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONVariant


class StrategyMode(enum.StrEnum):
    manual = "manual"
    self_learning = "self_learning"


class StrategyStatus(enum.StrEnum):
    draft = "draft"
    simulated = "simulated"
    live = "live"
    paused = "paused"
    stopped = "stopped"


class CreatedBy(enum.StrEnum):
    user = "user"
    feedback = "feedback"
    llm = "llm"


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[StrategyMode] = mapped_column(Enum(StrategyMode, native_enum=False, length=16))
    status: Mapped[StrategyStatus] = mapped_column(
        Enum(StrategyStatus, native_enum=False, length=16), default=StrategyStatus.draft
    )
    # Logical pointer to the active version (no FK to avoid a circular constraint).
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    version_num: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSONVariant)
    created_by: Mapped[CreatedBy] = mapped_column(Enum(CreatedBy, native_enum=False, length=16))
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
