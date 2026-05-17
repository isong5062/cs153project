"""20/50 EMA cross with ADX > threshold confirmation (plan §4.2).

Long when fast EMA > slow EMA and ADX > ``adx_min``. Exit when fast EMA crosses
back below slow EMA.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src.signals.indicators import adx, ema
from src.signals.strategies.base import (
    ACTION_FLAT,
    ACTION_LONG,
    BaseStrategy,
)


class TrendFollowing(BaseStrategy):
    name: ClassVar[str] = "trend_following"
    version: ClassVar[str] = "v1"
    default_params: ClassVar[dict[str, Any]] = {
        "ema_fast": 20,
        "ema_slow": 50,
        "adx_length": 14,
        "adx_min": 20.0,
    }
    param_grid: ClassVar[list[dict[str, Any]]] = [
        {"ema_fast": 20, "ema_slow": 50, "adx_min": 20.0},
        {"ema_fast": 10, "ema_slow": 30, "adx_min": 20.0},
        {"ema_fast": 20, "ema_slow": 50, "adx_min": 25.0},
    ]

    def required_history_bars(self) -> int:
        return int(self.params["ema_slow"]) + 20

    def _signals(self, data: pd.DataFrame) -> pd.DataFrame:
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)

        fast = ema(close, int(self.params["ema_fast"]))
        slow = ema(close, int(self.params["ema_slow"]))
        adx_ = adx(high, low, close, int(self.params["adx_length"]))
        adx_min = float(self.params["adx_min"])

        trend_up = fast > slow
        confirmed = trend_up & (adx_ > adx_min)

        # Enter on confirmation; hold while fast>slow; exit when cross-down.
        state = np.zeros(len(close), dtype=bool)
        holding = False
        tup = trend_up.to_numpy()
        conf_arr = confirmed.to_numpy()
        for i in range(len(close)):
            if holding:
                if not tup[i]:
                    holding = False
            else:
                if conf_arr[i]:
                    holding = True
            state[i] = holding

        action = np.where(state, ACTION_LONG, ACTION_FLAT)
        # Confidence scales with ADX strength above threshold, capped at 50 over.
        strength = ((adx_ - adx_min) / 50.0).clip(lower=0, upper=1).fillna(0.0)
        confidence = np.where(state, 0.5 + 0.5 * strength, 0.0)

        return pd.DataFrame(
            {"action": action, "confidence": confidence.astype(float)},
            index=close.index,
        )
