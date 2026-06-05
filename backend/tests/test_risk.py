import numpy as np
import pytest

from app.engine.risk.limits import (
    cap_total_leverage,
    cap_weight_by_risk,
    clamp_spec,
    evaluate_breakers,
    passes_correlation,
    validate_order,
)
from app.engine.risk.manager import RiskManager
from tests.factories import default_spec


def test_breaker_ok():
    s = evaluate_breakers(equity=100, day_start=100, week_start=100, peak=100)
    assert s.size_multiplier == 1.0 and not s.halted and not s.blocked


def test_breaker_daily_halve():
    s = evaluate_breakers(equity=98, day_start=100, week_start=100, peak=100)  # -2% day
    assert s.size_multiplier == 0.5 and not s.halted


def test_breaker_daily_flat():
    s = evaluate_breakers(equity=97, day_start=100, week_start=100, peak=100)  # -3% day
    assert s.halted and s.size_multiplier == 0.0 and not s.blocked


def test_breaker_weekly_and_daily_stack():
    # -2% on the day AND -5% on the week -> 0.5 * 0.5
    s = evaluate_breakers(equity=98, day_start=100, week_start=103.2, peak=100)
    assert s.size_multiplier == pytest.approx(0.25)


def test_breaker_drawdown_stop():
    s = evaluate_breakers(equity=90, day_start=90, week_start=90, peak=100)  # -10% from peak
    assert s.blocked and s.halted and s.size_multiplier == 0.0


def test_cap_weight_by_risk():
    assert cap_weight_by_risk(0.5, stop_pct=0.10, max_risk_per_trade=0.01) == pytest.approx(0.10)
    assert cap_weight_by_risk(0.05, stop_pct=0.10, max_risk_per_trade=0.01) == pytest.approx(0.05)


def test_cap_total_leverage():
    out = cap_total_leverage({"A": 1.0, "B": 1.0}, max_leverage=1.5)
    assert sum(out.values()) == pytest.approx(1.5)


def test_passes_correlation():
    a = np.array([1, -1, 1, -1], dtype=float)
    assert passes_correlation(a, [a.copy()], threshold=0.8) is False  # identical
    orthogonal = np.array([1, 1, -1, -1], dtype=float)
    assert passes_correlation(a, [orthogonal], threshold=0.8) is True


def test_clamp_spec_enforces_global_limits():
    spec = default_spec()
    spec.regime_rules["bull"].max_leverage = 3.0
    spec.risk_overrides.max_risk_per_trade = 0.05
    clamped = clamp_spec(spec)
    assert clamped.regime_rules["bull"].max_leverage == 1.5
    assert clamped.risk_overrides.max_risk_per_trade == 0.01


def test_validate_order():
    assert validate_order("AAPL", 10, halted=False, universe=["AAPL"])[0] is True
    assert validate_order("AAPL", 10, halted=True)[0] is False
    assert validate_order("AAPL", 0, halted=False)[0] is False
    assert validate_order("XYZ", 10, halted=False, universe=["AAPL"])[0] is False


def test_risk_manager_block_persists_until_reset(db_session):
    rm = RiskManager(db_session)
    # Trip a drawdown block.
    state = rm.evaluate(equity=90, day_start=90, week_start=90, peak=100)
    assert state.blocked and rm.is_blocked()

    # Even with healthy equity, the active block keeps it halted.
    healthy = rm.evaluate(equity=100, day_start=100, week_start=100, peak=100)
    assert healthy.halted and healthy.size_multiplier == 0.0

    block = rm.active_block()
    assert rm.reset_block(block.id) is True
    assert rm.is_blocked() is False
