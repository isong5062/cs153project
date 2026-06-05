"""Test data factories."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.engine.data.sources import empty_bars


def make_ohlcv(n: int = 300, seed: int = 0, start: str = "2023-01-02") -> pd.DataFrame:
    """Synthetic but valid OHLCV (naive-UTC business-day index)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.01, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range(start=start, periods=n, freq="B", name="ts")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx
    )


class FakeBarSource:
    """In-memory BarSource for tests (no network)."""

    def __init__(self, data: dict[tuple[str, str], pd.DataFrame]) -> None:
        self._data = data

    def get_bars(self, symbol, timeframe, start, end) -> pd.DataFrame:
        df = self._data.get((symbol, timeframe))
        return df.copy() if df is not None else empty_bars()


def make_fake_llm(spec=None, rationale: str = "synthetic optimization"):
    """An LLMProposer backed by a fake Anthropic client (no network/keys)."""
    import json

    from app.engine.learning.llm import LLMProposer

    proposed = spec or default_spec(mode="self_learning")
    payload = json.dumps(
        {"rationale": rationale, "spec": proposed.model_dump(mode="json")}
    )

    class _Block:
        def __init__(self, text):
            self.text = text
            self.type = "text"

    class _Usage:
        input_tokens = 100
        output_tokens = 50

    class _Resp:
        content = [_Block(payload)]
        usage = _Usage()

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    return LLMProposer(client=_Client())


def default_spec(mode: str = "manual", universe=("AAPL", "MSFT")):
    """A simple video-style regime->exposure strategy spec."""
    from app.engine.strategies.spec import RegimeRule, StrategySpec

    return StrategySpec(
        mode=mode,
        universe=list(universe),
        regime_rules={
            "crash": RegimeRule(target_exposure=0.0, max_leverage=1.0),
            "bear": RegimeRule(target_exposure=0.25, max_leverage=1.0),
            "neutral": RegimeRule(target_exposure=0.5, max_leverage=1.0),
            "bull": RegimeRule(target_exposure=0.95, max_leverage=1.25),
            "euphoria": RegimeRule(target_exposure=0.6, max_leverage=1.0),
        },
    )
