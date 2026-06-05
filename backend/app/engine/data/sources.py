"""Bar sources. Historical OHLCV via Alpaca (IEX feed); a Protocol allows fakes in tests."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from app.core.config import get_settings

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]
VALID_TIMEFRAMES = ("1Day", "5Min", "1Min")


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=BAR_COLUMNS, index=pd.DatetimeIndex([], name="ts"))


@runtime_checkable
class BarSource(Protocol):
    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame: ...


class AlpacaBarSource:
    """Historical bars from Alpaca on the free IEX feed."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        from alpaca.data.historical import StockHistoricalDataClient

        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_bars(self, symbol, timeframe, start, end) -> pd.DataFrame:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        if timeframe not in VALID_TIMEFRAMES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        if timeframe == "1Day":
            tf = TimeFrame.Day
        elif timeframe == "5Min":
            tf = TimeFrame(5, TimeFrameUnit.Minute)
        else:
            tf = TimeFrame(1, TimeFrameUnit.Minute)

        req = StockBarsRequest(
            symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, feed=DataFeed.IEX
        )
        result = self._client.get_stock_bars(req)
        df = result.df
        if df is None or df.empty:
            return empty_bars()
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level=0)
        out = df[BAR_COLUMNS].copy()
        out.index = pd.DatetimeIndex(out.index, name="ts")
        return out


def get_default_source() -> BarSource:
    """Construct the Alpaca source from settings, or raise a clear error."""
    s = get_settings()
    if not s.alpaca_api_key or not s.alpaca_secret_key:
        raise RuntimeError(
            "Alpaca API keys not configured. "
            "Set ALPACA_API_KEY and ALPACA_SECRET_KEY in backend/.env."
        )
    return AlpacaBarSource(s.alpaca_api_key, s.alpaca_secret_key)
