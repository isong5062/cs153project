"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.engine.strategies.spec import StrategySpec
from app.models.proposal import ProposalSource, ProposalStatus
from app.models.strategy import StrategyMode, StrategyStatus


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    mode: StrategyMode
    status: StrategyStatus
    current_version_id: int | None
    created_at: datetime


class CreateStrategyRequest(BaseModel):
    name: str
    spec: StrategySpec


class UpdateSpecRequest(BaseModel):
    spec: StrategySpec


class SetStatusRequest(BaseModel):
    status: StrategyStatus


class ApproveRequest(BaseModel):
    edited_spec: dict | None = None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version_num: int
    created_by: str
    created_at: datetime


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_id: int
    source: ProposalSource
    status: ProposalStatus
    rationale: str
    backtest_id: int | None
    created_at: datetime


class RegimeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    ts: datetime
    label: str
    confidence: float
    unstable: bool
