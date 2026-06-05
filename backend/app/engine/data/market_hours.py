"""NYSE (XNYS) market-hours helpers, used to gate the intraday loop."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pandas_market_calendars as mcal

_CAL = mcal.get_calendar("XNYS")


def _to_utc_ts(ts: datetime) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def is_regular_session(ts: datetime) -> bool:
    """True if `ts` falls within an NYSE regular trading session."""
    t = _to_utc_ts(ts)
    sched = _CAL.schedule(
        start_date=(t - pd.Timedelta(days=2)).date(),
        end_date=(t + pd.Timedelta(days=2)).date(),
    )
    if sched.empty:
        return False
    opens = pd.to_datetime(sched["market_open"], utc=True)
    closes = pd.to_datetime(sched["market_close"], utc=True)
    return bool(((opens <= t) & (t <= closes)).any())


def regular_session_dates(start: date, end: date) -> list[date]:
    """List of NYSE trading dates in [start, end]."""
    sched = _CAL.schedule(start_date=str(start), end_date=str(end))
    return [ts.date() for ts in sched.index]
