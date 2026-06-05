"""Strategy specification (the validated, diffable DSL).

This is what "logic" means for a strategy: regime -> allocation rules plus entry/
exit condition trees over features. Both the manual editor and the #4 LLM proposer
produce edits to this schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.engine.regime.hmm import CANONICAL_LABELS
from app.models.strategy import StrategyMode

Op = Literal["<", "<=", ">", ">=", "==", "!="]


class Condition(BaseModel):
    indicator: str
    op: Op
    value: float


class ConditionGroup(BaseModel):
    logic: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


class RegimeRule(BaseModel):
    target_exposure: float = Field(ge=0.0, le=5.0)
    max_leverage: float = Field(default=1.0, ge=0.0, le=5.0)
    entry: ConditionGroup = Field(default_factory=ConditionGroup)
    exit: ConditionGroup = Field(default_factory=ConditionGroup)


class IndicatorSpec(BaseModel):
    name: str
    period: int = Field(ge=1, le=500)


class RiskOverrides(BaseModel):
    # Clamped to global limits by the risk layer (Phase 4).
    max_risk_per_trade: float = Field(default=0.01, ge=0.0, le=0.1)


class StrategySpec(BaseModel):
    mode: StrategyMode = StrategyMode.manual
    universe: list[str] = Field(min_length=1)
    regime_rules: dict[str, RegimeRule]
    indicators: list[IndicatorSpec] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)
    risk_overrides: RiskOverrides = Field(default_factory=RiskOverrides)

    @field_validator("universe")
    @classmethod
    def _normalize_universe(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(s.strip().upper() for s in v if s.strip()))
        if not out:
            raise ValueError("universe must contain at least one symbol")
        return out

    @field_validator("regime_rules")
    @classmethod
    def _check_regime_labels(cls, v: dict) -> dict:
        bad = set(v) - set(CANONICAL_LABELS)
        if bad:
            raise ValueError(f"unknown regime labels: {sorted(bad)}")
        return v
