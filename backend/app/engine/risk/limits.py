"""Hardcoded global risk limits + pure risk math.

These thresholds are independent of any strategy or AI proposal. The clamp
functions enforce "a strategy may be more conservative, never looser."
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.engine.strategies.spec import RiskOverrides, StrategySpec


@dataclass(frozen=True)
class RiskLimits:
    daily_loss_halve: float = 0.02  # -2% on the day -> halve sizes
    daily_loss_flat: float = 0.03  # -3% on the day -> close everything
    weekly_loss_halve: float = 0.05  # -5% on the week -> halve sizes
    drawdown_stop: float = 0.10  # -10% from peak -> full stop + manual reset
    max_risk_per_trade: float = 0.01  # global cap
    max_leverage: float = 1.5  # global gross-exposure cap
    max_correlation: float = 0.8


GLOBAL_LIMITS = RiskLimits()


@dataclass
class RiskState:
    size_multiplier: float = 1.0
    halted: bool = False  # flatten + block new entries
    blocked: bool = False  # drawdown stop -> requires manual reset
    reasons: list[str] = field(default_factory=list)


def evaluate_breakers(
    equity: float,
    day_start: float,
    week_start: float,
    peak: float,
    limits: RiskLimits = GLOBAL_LIMITS,
) -> RiskState:
    daily = (equity / day_start - 1.0) if day_start > 0 else 0.0
    weekly = (equity / week_start - 1.0) if week_start > 0 else 0.0
    drawdown = (equity / peak - 1.0) if peak > 0 else 0.0

    eps = 1e-9  # tolerance so an exact-threshold loss still trips despite float error
    if drawdown <= -limits.drawdown_stop + eps:
        return RiskState(0.0, halted=True, blocked=True, reasons=["drawdown_stop"])
    if daily <= -limits.daily_loss_flat + eps:
        return RiskState(0.0, halted=True, blocked=False, reasons=["daily_loss_flat"])

    mult = 1.0
    reasons: list[str] = []
    if daily <= -limits.daily_loss_halve + eps:
        mult *= 0.5
        reasons.append("daily_loss_halve")
    if weekly <= -limits.weekly_loss_halve + eps:
        mult *= 0.5
        reasons.append("weekly_loss_halve")
    return RiskState(mult, halted=False, blocked=False, reasons=reasons)


def cap_weight_by_risk(
    weight: float, stop_pct: float, max_risk_per_trade: float = GLOBAL_LIMITS.max_risk_per_trade
) -> float:
    """Cap a position weight so risk (weight * stop distance) <= max risk/trade."""
    if stop_pct <= 0:
        return weight
    return min(weight, max_risk_per_trade / stop_pct)


def cap_total_leverage(
    weights: dict[str, float], max_leverage: float = GLOBAL_LIMITS.max_leverage
) -> dict[str, float]:
    gross = sum(abs(w) for w in weights.values())
    if gross <= max_leverage or gross == 0:
        return dict(weights)
    scale = max_leverage / gross
    return {s: w * scale for s, w in weights.items()}


def passes_correlation(
    candidate: np.ndarray,
    existing: list[np.ndarray],
    threshold: float = GLOBAL_LIMITS.max_correlation,
) -> bool:
    candidate = np.asarray(candidate, dtype=float)
    for series in existing:
        series = np.asarray(series, dtype=float)
        n = min(len(candidate), len(series))
        if n < 3:
            continue
        c = np.corrcoef(candidate[-n:], series[-n:])[0, 1]
        if np.isfinite(c) and abs(c) > threshold:
            return False
    return True


def clamp_risk_overrides(
    overrides: RiskOverrides, limits: RiskLimits = GLOBAL_LIMITS
) -> RiskOverrides:
    return RiskOverrides(
        max_risk_per_trade=min(overrides.max_risk_per_trade, limits.max_risk_per_trade)
    )


def clamp_spec(spec: StrategySpec, limits: RiskLimits = GLOBAL_LIMITS) -> StrategySpec:
    """Bound a spec's leverage + risk overrides to global limits (never looser)."""
    new_rules = {
        label: rule.model_copy(update={"max_leverage": min(rule.max_leverage, limits.max_leverage)})
        for label, rule in spec.regime_rules.items()
    }
    return spec.model_copy(
        update={
            "regime_rules": new_rules,
            "risk_overrides": clamp_risk_overrides(spec.risk_overrides, limits),
        }
    )


def validate_order(
    symbol: str, qty: float, halted: bool, universe: list[str] | None = None
) -> tuple[bool, str]:
    if halted:
        return False, "trading halted"
    if qty <= 0:
        return False, "qty must be positive"
    if universe is not None and symbol not in universe:
        return False, "symbol not in universe"
    return True, "ok"
