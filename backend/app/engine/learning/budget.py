"""Cost-cap accounting for self-learning (#4) LLM spend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.proposal import TokenUsage
from app.models.strategy import Strategy, StrategyMode


@dataclass(frozen=True)
class LearningBudget:
    max_self_learning_strategies: int = 5
    daily_token_budget: int = 200_000


def tokens_used_today(db: Session) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    rows = db.query(TokenUsage).filter(TokenUsage.ts >= start).all()
    return sum(r.input_tokens + r.output_tokens for r in rows)


def count_self_learning_strategies(db: Session) -> int:
    return db.query(Strategy).filter(Strategy.mode == StrategyMode.self_learning).count()


def can_run_llm(db: Session, budget: LearningBudget) -> bool:
    return tokens_used_today(db) < budget.daily_token_budget


def can_add_self_learning_strategy(db: Session, budget: LearningBudget) -> bool:
    return count_self_learning_strategies(db) < budget.max_self_learning_strategies


def record_usage(
    db: Session, strategy_id: int | None, purpose: str, input_tokens: int, output_tokens: int
) -> TokenUsage:
    u = TokenUsage(
        strategy_id=strategy_id,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u
