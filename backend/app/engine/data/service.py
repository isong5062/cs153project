"""MarketDataService: fetch, store, and load bars + engineered features."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.engine.data.sources import BarSource, empty_bars, get_default_source
from app.engine.features.engineering import compute_features
from app.models.market import Bar, FeatureRow


def _to_naive_utc(ts) -> datetime:
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.to_pydatetime()


def _naive_utc_index(idx) -> pd.DatetimeIndex:
    di = pd.DatetimeIndex(idx)
    if di.tz is not None:
        di = di.tz_convert("UTC").tz_localize(None)
    return di


class MarketDataService:
    def __init__(self, db: Session, source: BarSource | None = None) -> None:
        self._db = db
        self._source = source

    def _src(self) -> BarSource:
        return self._source or get_default_source()

    # --- fetch + store ---
    def fetch_and_store(self, symbol, timeframe, start, end) -> int:
        df = self._src().get_bars(symbol, timeframe, start, end)
        return self.store_bars(symbol, timeframe, df)

    def store_bars(self, symbol, timeframe, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        ts_list = [t.to_pydatetime() for t in _naive_utc_index(df.index)]
        existing = {
            r[0]
            for r in self._db.query(Bar.ts)
            .filter(Bar.symbol == symbol, Bar.timeframe == timeframe, Bar.ts.in_(ts_list))
            .all()
        }
        rows = [
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for ts, (_, row) in zip(ts_list, df.iterrows(), strict=True)
            if ts not in existing
        ]
        if rows:
            self._db.add_all(rows)
            self._db.commit()
        return len(rows)

    def upsert_bar(self, symbol, timeframe, ts, open_, high, low, close, volume) -> bool:
        """Insert or update a single bar. Returns True if newly inserted."""
        ts = _to_naive_utc(ts)
        existing = (
            self._db.query(Bar)
            .filter_by(symbol=symbol, timeframe=timeframe, ts=ts)
            .one_or_none()
        )
        if existing is not None:
            existing.open, existing.high, existing.low, existing.close, existing.volume = (
                float(open_),
                float(high),
                float(low),
                float(close),
                float(volume),
            )
            self._db.commit()
            return False
        self._db.add(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
        self._db.commit()
        return True

    # --- load ---
    def load_bars(self, symbol, timeframe, start=None, end=None) -> pd.DataFrame:
        q = self._db.query(Bar).filter(Bar.symbol == symbol, Bar.timeframe == timeframe)
        if start is not None:
            q = q.filter(Bar.ts >= _to_naive_utc(start))
        if end is not None:
            q = q.filter(Bar.ts <= _to_naive_utc(end))
        recs = q.order_by(Bar.ts.asc()).all()
        if not recs:
            return empty_bars()
        idx = pd.DatetimeIndex([r.ts for r in recs], name="ts")
        return pd.DataFrame(
            {
                "open": [r.open for r in recs],
                "high": [r.high for r in recs],
                "low": [r.low for r in recs],
                "close": [r.close for r in recs],
                "volume": [r.volume for r in recs],
            },
            index=idx,
        )

    # --- features ---
    def compute_and_store_features(self, symbol, timeframe) -> int:
        bars = self.load_bars(symbol, timeframe)
        if bars.empty:
            return 0
        feats = compute_features(bars)
        ts_list = [t.to_pydatetime() for t in pd.DatetimeIndex(feats.index)]
        existing = {
            r[0]
            for r in self._db.query(FeatureRow.ts)
            .filter(
                FeatureRow.symbol == symbol,
                FeatureRow.timeframe == timeframe,
                FeatureRow.ts.in_(ts_list),
            )
            .all()
        }
        rows = []
        for ts, (_, frow) in zip(ts_list, feats.iterrows(), strict=True):
            if ts in existing:
                continue
            values = {k: (None if pd.isna(v) else float(v)) for k, v in frow.items()}
            rows.append(FeatureRow(symbol=symbol, timeframe=timeframe, ts=ts, values=values))
        if rows:
            self._db.add_all(rows)
            self._db.commit()
        return len(rows)

    def load_features(self, symbol, timeframe) -> pd.DataFrame:
        recs = (
            self._db.query(FeatureRow)
            .filter(FeatureRow.symbol == symbol, FeatureRow.timeframe == timeframe)
            .order_by(FeatureRow.ts.asc())
            .all()
        )
        if not recs:
            return pd.DataFrame()
        idx = pd.DatetimeIndex([r.ts for r in recs], name="ts")
        return pd.DataFrame([r.values for r in recs], index=idx)
