"""#2 adaptive parameter feedback.

Nudges regime target exposures from realized per-regime performance: shrink
exposure where a regime has been losing, grow it (bounded) where it's winning.
Deterministic; produces a proposal (clamped) or None if nothing changes.
"""

from __future__ import annotations

from app.engine.risk.limits import clamp_spec
from app.engine.strategies.spec import StrategySpec


def propose_from_performance(
    spec: StrategySpec,
    regime_breakdown: dict,
    step: float = 0.1,
    min_samples: int = 5,
    gain_threshold: float = 0.0005,
) -> StrategySpec | None:
    new_rules = {}
    changed = False
    for label, rule in spec.regime_rules.items():
        target = rule.target_exposure
        stats = regime_breakdown.get(label)
        if stats and stats.get("n", 0) >= min_samples:
            mr = stats.get("mean_return", 0.0)
            if mr < 0:
                target = max(0.0, rule.target_exposure - step)
            elif mr > gain_threshold:
                target = min(rule.max_leverage, rule.target_exposure + step)
        if abs(target - rule.target_exposure) > 1e-9:
            changed = True
        new_rules[label] = rule.model_copy(update={"target_exposure": target})

    if not changed:
        return None
    return clamp_spec(spec.model_copy(update={"regime_rules": new_rules}))
