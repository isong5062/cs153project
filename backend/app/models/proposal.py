"""Self-learning proposals + LLM token-usage accounting."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONVariant


class ProposalSource(enum.StrEnum):
    feedback = "feedback"  # #2 adaptive parameter feedback
    llm = "llm"  # #4 Claude reasoning
    user = "user"


class ProposalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[ProposalSource] = mapped_column(
        Enum(ProposalSource, native_enum=False, length=12)
    )
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, native_enum=False, length=12), default=ProposalStatus.pending
    )
    rationale: Mapped[str] = mapped_column(Text, default="")
    proposed_spec: Mapped[dict] = mapped_column(JSONVariant)
    backtest_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # mandatory preview
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
