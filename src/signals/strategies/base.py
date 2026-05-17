"""Strategy protocol — the shape every strategy obeys.

Design notes (plan §6):
- `generate_signals(df)` is a pure function: same inputs → same outputs.
- The output is a DataFrame aligned to the input's index with two columns:
    * ``action``: one of {"long", "flat", "short"}
    * ``confidence``: float in [0, 1]
- Property invariant: the signal set is self-consistent per bar
  (we never emit contradictory directions for the same symbol at the same ts).
- Strategies never look at future bars — they operate on OHLCV up to each index.
  Indicator libraries are safe because they align windows with ``shift(1)`` where
  needed in the strategy itself (see below).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

import pandas as pd

ACTION_LONG = "long"
ACTION_FLAT = "flat"
ACTION_SHORT = "short"
VALID_ACTIONS: frozenset[str] = frozenset({ACTION_LONG, ACTION_FLAT, ACTION_SHORT})


class Strategy(Protocol):
    """Structural type all strategies satisfy."""

    name: str
    version: str
    params: dict[str, Any]

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame: ...

    def required_history_bars(self) -> int: ...


@dataclass
class BaseStrategy:
    """Concrete base — subclasses override ``name``, ``default_params``, and
    implement ``_signals``. Parameter grids are optional and drive walk-forward
    optimization (plan §9.1)."""

    name: ClassVar[str] = "base"
    version: ClassVar[str] = "v1"
    default_params: ClassVar[dict[str, Any]] = {}
    param_grid: ClassVar[list[dict[str, Any]]] = []

    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        merged = dict(self.default_params)
        merged.update(self.params or {})
        self.params = merged

    def required_history_bars(self) -> int:
        return 50

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return _empty_signal_frame(data.index)
        out = self._signals(data)
        _validate(out, data)
        return out

    def _signals(self, data: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


def _empty_signal_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {"action": pd.Series(dtype="object"), "confidence": pd.Series(dtype="float64")},
        index=index,
    )


def _validate(signals: pd.DataFrame, data: pd.DataFrame) -> None:
    if list(signals.columns[:2]) != ["action", "confidence"]:
        raise ValueError("signal frame must have columns [action, confidence] first")
    if not signals.index.equals(data.index):
        raise ValueError("signal frame index must equal data index")
    invalid = set(signals["action"].dropna().unique()) - VALID_ACTIONS
    if invalid:
        raise ValueError(f"invalid actions: {invalid}")
    conf = signals["confidence"].dropna()
    if ((conf < 0) | (conf > 1)).any():
        raise ValueError("confidence must be in [0, 1]")


def signals_to_entries_exits(signals: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Convert an ``action`` column to boolean long-entry / long-exit Series.

    v1 baselines are long-only; shorts are currently mapped to "flat". Phase 2+
    can extend to short_entries / short_exits once the broker path supports them.
    """
    action = signals["action"].fillna(ACTION_FLAT)
    is_long = action == ACTION_LONG
    entries = is_long & ~is_long.shift(1, fill_value=False)
    exits = ~is_long & is_long.shift(1, fill_value=False)
    return entries, exits
