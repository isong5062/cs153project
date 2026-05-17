"""Fixed-fractional position sizing (plan §4.4).

Shares = floor((equity * risk_pct) / max(entry - stop, tick))

Caps:
  - max position notional = equity * max_position_pct
  - must leave at least one full share of buffer vs buying power
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class SizerInput:
    equity: Decimal
    buying_power: Decimal
    entry_price: Decimal
    stop_price: Decimal
    risk_per_trade_pct: float  # e.g. 0.01
    max_position_pct: float    # e.g. 0.05


def size_position(inp: SizerInput) -> int:
    """Return an integer share count. 0 means "don't trade".

    Returns 0 when risk per share is zero/negative, stop is above entry (long),
    or the cap would round down to zero shares.
    """
    risk_per_share = inp.entry_price - inp.stop_price
    if risk_per_share <= 0:
        return 0

    risk_budget = Decimal(str(inp.risk_per_trade_pct)) * inp.equity
    raw = risk_budget / risk_per_share

    max_notional = Decimal(str(inp.max_position_pct)) * inp.equity
    by_notional = max_notional / inp.entry_price if inp.entry_price > 0 else raw
    by_bp = inp.buying_power / inp.entry_price if inp.entry_price > 0 else raw

    qty = min(raw, by_notional, by_bp)
    return max(0, math.floor(float(qty)))
