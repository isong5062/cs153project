"""Strategy registry.

Strategies register themselves here so the tournament, backtester, and live
trader can enumerate them uniformly. New strategies added as modules must be
added to :data:`REGISTRY`.
"""

from __future__ import annotations

from typing import Any

from src.signals.strategies.base import BaseStrategy, Strategy
from src.signals.strategies.breakout import Breakout
from src.signals.strategies.mean_reversion import MeanReversion
from src.signals.strategies.trend_following import TrendFollowing

REGISTRY: dict[str, type[BaseStrategy]] = {
    MeanReversion.name: MeanReversion,
    TrendFollowing.name: TrendFollowing,
    Breakout.name: Breakout,
}


def get(name: str, **params: Any) -> BaseStrategy:
    if name not in REGISTRY:
        raise KeyError(f"Unknown strategy: {name}. Available: {sorted(REGISTRY)}")
    return REGISTRY[name](params=params)


def all_default() -> list[BaseStrategy]:
    return [cls(params={}) for cls in REGISTRY.values()]


__all__ = [
    "BaseStrategy",
    "Breakout",
    "MeanReversion",
    "REGISTRY",
    "Strategy",
    "TrendFollowing",
    "all_default",
    "get",
]
