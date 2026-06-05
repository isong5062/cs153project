"""Read-only settings: limits, caps, and whether keys are configured (never the keys)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.core.config import get_settings
from app.engine.learning.budget import LearningBudget
from app.engine.risk.limits import GLOBAL_LIMITS

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def read_settings():
    s = get_settings()
    budget = LearningBudget()
    return {
        "regime_symbol": "SPY",
        "default_universe": ["SPY", "AAPL", "MSFT", "NVDA"],
        "bar_timeframe": "5Min",
        "paper_only": True,
        "risk_limits": asdict(GLOBAL_LIMITS),
        "budget": {
            "max_self_learning_strategies": budget.max_self_learning_strategies,
            "daily_token_budget": budget.daily_token_budget,
        },
        "alpaca_configured": bool(s.alpaca_api_key and s.alpaca_secret_key),
        "anthropic_configured": bool(s.anthropic_api_key),
    }
