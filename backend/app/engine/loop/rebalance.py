"""Rebalancing: turn target weights into orders via an executor.

When the risk layer halts a strategy, we flatten instead of opening anything.
"""

from __future__ import annotations

from app.engine.risk.limits import RiskState, validate_order
from app.engine.strategies.evaluator import evaluate
from app.engine.strategies.spec import StrategySpec


def target_weights(
    spec: StrategySpec,
    regime_label: str,
    confidence: float,
    unstable: bool,
    risk_state: RiskState,
    features_by_symbol: dict | None = None,
) -> dict[str, float]:
    if risk_state.halted:
        return {s: 0.0 for s in spec.universe}
    w = evaluate(
        spec, regime_label, features_by_symbol or {}, confidence=confidence, unstable=unstable
    )
    return {s: x * risk_state.size_multiplier for s, x in w.items()}


def rebalance_strategy(
    strategy_id: int,
    spec: StrategySpec,
    executor,
    price_map: dict[str, float],
    regime_label: str,
    confidence: float,
    unstable: bool,
    risk_state: RiskState,
    features_by_symbol: dict | None = None,
) -> list:
    if risk_state.halted:
        executor.flatten(strategy_id, price_map)
        return []

    targets = target_weights(
        spec, regime_label, confidence, unstable, risk_state, features_by_symbol
    )
    equity = executor.equity(strategy_id, price_map)
    positions = executor.positions(strategy_id)

    orders = []
    for sym in spec.universe:
        price = price_map.get(sym)
        if not price or price <= 0:
            continue
        target_qty = round((targets.get(sym, 0.0) * equity) / price)
        cur_qty = positions[sym].qty if sym in positions else 0.0
        delta = target_qty - cur_qty
        if abs(delta) < 1:
            continue
        side = "buy" if delta > 0 else "sell"
        ok, _reason = validate_order(sym, abs(delta), halted=False, universe=spec.universe)
        if not ok:
            continue
        orders.append(executor.submit(strategy_id, sym, side, abs(delta), price))
    return orders
