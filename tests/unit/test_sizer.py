"""Unit tests for the fixed-fractional position sizer."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from src.risk.sizer import SizerInput, size_position


def _inp(**kw) -> SizerInput:
    defaults = dict(
        equity=Decimal("100000"),
        buying_power=Decimal("100000"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        risk_per_trade_pct=0.01,
        max_position_pct=0.05,
    )
    defaults.update(kw)
    return SizerInput(**defaults)


def test_basic_sizing_formula():
    # risk budget = 1000, risk per share = 5 → 200 shares; cap = 5000/100 = 50.
    assert size_position(_inp()) == 50


def test_zero_when_stop_above_entry():
    assert size_position(_inp(stop_price=Decimal("110"))) == 0


def test_zero_when_stop_equals_entry():
    assert size_position(_inp(stop_price=Decimal("100"))) == 0


def test_capped_by_buying_power():
    # 500 bp, $100 share → max 5 shares regardless of risk math.
    assert size_position(_inp(buying_power=Decimal("500"))) == 5


def test_capped_by_notional():
    # max_position_pct 1% of 100k = 1000 → 10 shares at $100.
    assert size_position(_inp(max_position_pct=0.01)) == 10


@given(
    equity=st.decimals(min_value=Decimal("1000"), max_value=Decimal("1000000"),
                       allow_nan=False, allow_infinity=False, places=2),
    entry=st.decimals(min_value=Decimal("1"), max_value=Decimal("1000"),
                      allow_nan=False, allow_infinity=False, places=2),
    stop_gap=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("50"),
                         allow_nan=False, allow_infinity=False, places=2),
    risk_pct=st.floats(min_value=0.001, max_value=0.05),
    max_pos_pct=st.floats(min_value=0.001, max_value=0.2),
)
def test_sizer_never_exceeds_caps(equity, entry, stop_gap, risk_pct, max_pos_pct):
    assume(stop_gap < entry)
    stop = entry - stop_gap
    qty = size_position(
        _inp(
            equity=equity,
            buying_power=equity,
            entry_price=entry,
            stop_price=stop,
            risk_per_trade_pct=risk_pct,
            max_position_pct=max_pos_pct,
        )
    )
    assert qty >= 0
    notional = Decimal(qty) * entry
    # Caps: notional ≤ equity * max_position_pct, and ≤ buying power.
    assert notional <= Decimal(str(max_pos_pct)) * equity + entry  # +1 share tolerance from floor
    assert notional <= equity + entry
    # Risk budget upper bound (plus 1 share tolerance).
    assert Decimal(qty) * stop_gap <= Decimal(str(risk_pct)) * equity + stop_gap
