"""Strategy evaluator: regime + features -> target portfolio weights.

Deterministic and side-effect free. Output is a dict {symbol: target_weight},
where target_weight is the fraction of portfolio equity to hold in that symbol.
"""

from __future__ import annotations

import math
import operator

import pandas as pd

from app.engine.strategies.spec import ConditionGroup, StrategySpec

_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def latest_features(df: pd.DataFrame) -> dict[str, float]:
    """Last feature row as a plain dict (NaN -> None)."""
    if df is None or df.empty:
        return {}
    row = df.iloc[-1]
    return {k: (None if pd.isna(v) else float(v)) for k, v in row.items()}


def _passes(group: ConditionGroup, feats: dict | None) -> bool:
    if group is None or not group.conditions:
        return True
    if not feats:
        return False
    results = []
    for c in group.conditions:
        val = feats.get(c.indicator)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            results.append(False)
        else:
            results.append(_OPS[c.op](val, c.value))
    return all(results) if group.logic == "all" else any(results)


def evaluate(
    spec: StrategySpec,
    regime_label: str,
    features_by_symbol: dict[str, dict],
    *,
    confidence: float = 1.0,
    unstable: bool = False,
) -> dict[str, float]:
    rule = spec.regime_rules.get(regime_label)
    if rule is None:
        return {s: 0.0 for s in spec.universe}

    exposure = min(rule.target_exposure, rule.max_leverage)
    if unstable:
        exposure *= float(spec.params.get("unstable_scale", 0.5))
    if confidence < float(spec.params.get("min_confidence", 0.0)):
        return {s: 0.0 for s in spec.universe}

    eligible = [s for s in spec.universe if _passes(rule.entry, features_by_symbol.get(s))]
    if not eligible or exposure <= 0:
        return {s: 0.0 for s in spec.universe}

    weight = exposure / len(eligible)
    return {s: (weight if s in eligible else 0.0) for s in spec.universe}
