"""DataProvider contract smoke tests.

Every provider in src.data.providers must satisfy this contract. When we add
a new provider, it should pass these same assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.data.providers.base import BAR_COLUMNS, DataProvider
from src.persistence.models import Timeframe


class _StubProvider(DataProvider):
    name = "stub"

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: Timeframe = Timeframe.DAY,
    ) -> pd.DataFrame:
        df = self._frame.loc[(self._frame.index >= start) & (self._frame.index <= end)]
        return df.copy()


def _make_frame(n: int = 10) -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    idx = pd.DatetimeIndex(
        [start + timedelta(days=i) for i in range(n)], tz="UTC", name="ts"
    )
    return pd.DataFrame(
        {
            "open": range(100, 100 + n),
            "high": range(101, 101 + n),
            "low": range(99, 99 + n),
            "close": range(100, 100 + n),
            "volume": [1_000_000] * n,
        },
        index=idx,
    )


@pytest.fixture
def provider() -> _StubProvider:
    return _StubProvider(_make_frame())


def test_returned_frame_has_required_columns(provider: _StubProvider) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 5, tzinfo=UTC)
    df = provider.get_bars("SPY", start, end)
    for col in BAR_COLUMNS:
        assert col in df.columns, f"missing required column: {col}"


def test_index_is_utc_and_named_ts(provider: _StubProvider) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 5, tzinfo=UTC)
    df = provider.get_bars("SPY", start, end)
    assert df.index.name == "ts"
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"


def test_index_is_sorted_ascending(provider: _StubProvider) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 10, tzinfo=UTC)
    df = provider.get_bars("SPY", start, end)
    assert df.index.is_monotonic_increasing


def test_respects_window(provider: _StubProvider) -> None:
    start = datetime(2025, 1, 3, tzinfo=UTC)
    end = datetime(2025, 1, 6, tzinfo=UTC)
    df = provider.get_bars("SPY", start, end)
    assert df.index.min() >= start
    assert df.index.max() <= end


def test_batch_default_dispatches_per_symbol(provider: _StubProvider) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 5, tzinfo=UTC)
    out = provider.get_bars_batch(["SPY", "QQQ"], start, end)
    assert set(out.keys()) == {"SPY", "QQQ"}
    for df in out.values():
        assert list(BAR_COLUMNS) == list(df.columns)[: len(BAR_COLUMNS)]
