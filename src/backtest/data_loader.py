"""Load cached bars from Postgres into a pandas DataFrame keyed by symbol.

Returned frames are float-typed (Decimal → float) and indexed by UTC timestamp.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select

from src.persistence.db import session_scope
from src.persistence.models import Bar, Timeframe


def load_bars(
    symbols: list[str],
    start: datetime,
    end: datetime,
    timeframe: Timeframe = Timeframe.DAY,
) -> dict[str, pd.DataFrame]:
    """Return {symbol: DataFrame[open,high,low,close,volume]}. Missing symbols omitted."""
    stmt = (
        select(Bar.symbol, Bar.ts, Bar.open, Bar.high, Bar.low, Bar.close, Bar.volume)
        .where(
            Bar.symbol.in_(symbols),
            Bar.timeframe == timeframe,
            Bar.ts >= start,
            Bar.ts <= end,
        )
        .order_by(Bar.symbol, Bar.ts)
    )
    out: dict[str, pd.DataFrame] = {}
    with session_scope() as session:
        rows = session.execute(stmt).all()

    if not rows:
        return out

    df = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype("int64")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    for symbol, group in df.groupby("symbol", sort=False):
        frame = group.drop(columns=["symbol"]).set_index("ts").sort_index()
        out[str(symbol)] = frame
    return out


def aligned_close_matrix(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a date-aligned close-price matrix across symbols (union of dates)."""
    if not bars:
        return pd.DataFrame()
    return pd.DataFrame({sym: df["close"] for sym, df in bars.items()}).sort_index()
