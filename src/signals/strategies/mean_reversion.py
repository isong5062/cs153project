"""Bollinger-band + RSI mean-reversion (plan §4.2).

Long when:
  - close closes below the lower Bollinger band (``length`` SMA ± ``n_std``·σ), and
  - RSI(``rsi_length``) < ``rsi_oversold``.
Exit:
  - close reverts back above the Bollinger mid-band, or
  - RSI crosses back above 50.

Long-only in v1.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src.signals.indicators import bollinger, rsi
from src.signals.strategies.base import (
    ACTION_FLAT,
    ACTION_LONG,
    BaseStrategy,
)


class MeanReversion(BaseStrategy):
    name: ClassVar[str] = "mean_reversion"
    version: ClassVar[str] = "v1"
    default_params: ClassVar[dict[str, Any]] = {
        "bb_length": 20,
        "bb_std": 2.0,
        "rsi_length": 14,
        "rsi_oversold": 30.0,
    }
    param_grid: ClassVar[list[dict[str, Any]]] = [
        {"bb_length": 20, "bb_std": 2.0, "rsi_oversold": 30.0},
        {"bb_length": 20, "bb_std": 2.5, "rsi_oversold": 25.0},
        {"bb_length": 30, "bb_std": 2.0, "rsi_oversold": 30.0},
    ]

    def required_history_bars(self) -> int:
        return int(max(self.params["bb_length"], self.params["rsi_length"])) + 10

    def _signals(self, data: pd.DataFrame) -> pd.DataFrame:
        close = data["close"].astype(float)
        lower, mid, _ = bollinger(close, int(self.params["bb_length"]), float(self.params["bb_std"]))
        rsi_ = rsi(close, int(self.params["rsi_length"]))

        oversold = float(self.params["rsi_oversold"])
        entry_cond = (close < lower) & (rsi_ < oversold)
        exit_cond = (close > mid) | (rsi_ > 50)

        # Stateful long/flat: enter on entry_cond, stay until exit_cond.
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
        # Confidence scales with how far RSI is below oversold (clipped).
        depth = ((oversold - rsi_) / oversold).clip(lower=0, upper=1).fillna(0.0)
        confidence = np.where(state, 0.5 + 0.5 * depth, 0.0)

        return pd.DataFrame(
            {"action": action, "confidence": confidence.astype(float)},
            index=close.index,
        )
