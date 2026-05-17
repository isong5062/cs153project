"""Risk: position sizing + hard-rule guards.

The guards in this package have *veto power* over every strategy and agent —
LLMs cannot override them (plan §4.5). Keep the code in here pure and
property-tested.
"""

from src.risk.guards import (
    GuardDecision,
    GuardVerdict,
    RiskContext,
    TradeProposal,
    evaluate_all,
)
from src.risk.sizer import SizerInput, size_position

__all__ = [
    "GuardDecision",
    "GuardVerdict",
    "RiskContext",
    "SizerInput",
    "TradeProposal",
    "evaluate_all",
    "size_position",
]
