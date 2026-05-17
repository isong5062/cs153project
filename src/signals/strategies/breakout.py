"""Donchian-channel breakout with volume confirmation (plan §4.2).

Long when close breaks above the prior ``length``-bar high (exclusive of today)
and volume > ``vol_mult`` × average volume. Exit when close drops below the
``exit_length``-bar low.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src.signals.indicators import donchian
from src.signals.strategies.base import (
    ACTION_FLAT,
    ACTION_LONG,
    BaseStrategy,
)


class Breakout(BaseStrategy):
    name: ClassVar[str] = "breakout"
    version: ClassVar[str] = "v1"
    default_params: ClassVar[dict[str, Any]] = {
        "length": 20,
        "exit_length": 10,
        "vol_length": 20,
        "vol_mult": 1.5,
    }
    param_grid: ClassVar[list[dict[str, Any]]] = [
        {"length": 20, "exit_length": 10, "vol_mult": 1.5},
        {"length": 55, "exit_length": 20, "vol_mult": 1.2},
        {"length": 20, "exit_length": 10, "vol_mult": 2.0},
    ]

    def required_history_bars(self) -> int:
        return int(max(self.params["length"], self.params["vol_length"])) + 5

    def _signals(self, data: pd.DataFrame) -> pd.DataFrame:
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        volume = data["volume"].astype(float)

        # Use yesterday's channel to avoid look-ahead — the "prior N-bar" high/low.
        _, upper = donchian(high, low, int(self.params["length"]))
        lower_exit, _ = donchian(high, low, int(self.params["exit_length"]))
        upper_prev = upper.shift(1)
        lower_prev = lower_exit.shift(1)

        avg_vol = volume.rolling(int(self.params["vol_length"]), min_periods=int(self.params["vol_length"])).mean()
        vol_mult = float(self.params["vol_mult"])

        entry_cond = (close > upper_prev) & (volume > vol_mult * avg_vol)
        exit_cond = close < lower_prev

        state = np.zeros(len(close), dtype=bool)
        holding = False
        ec = entry_cond.to_numpy()
        xc = exit_cond.to_numpy()
        for i in range(len(close)):
            if holding:
                if xc[i]:
                    holding = False
            else:
                if ec[i]:
                    holding = True
            state[i] = holding

        action = np.where(state, ACTION_LONG, ACTION_FLAT)
        # Confidence scales with how far volume exceeded the multiplier.
        excess = ((volume / (avg_vol * vol_mult)) - 1).clip(lower=0, upper=1).fillna(0.0)
        confidence = np.where(state, 0.5 + 0.5 * excess, 0.0)

        return pd.DataFrame(
            {"action": action, "confidence": confidence.astype(float)},
            index=close.index,
        )
