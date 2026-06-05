import datetime as dt

from app.engine.data.market_hours import is_regular_session, regular_session_dates

UTC = dt.UTC


def test_regular_session_open():
    # 2025-01-02 (Thu) 15:00 UTC = 10:00 ET -> open
    assert is_regular_session(dt.datetime(2025, 1, 2, 15, 0, tzinfo=UTC)) is True


def test_premarket_closed():
    # 2025-01-02 13:00 UTC = 08:00 ET -> pre-market
    assert is_regular_session(dt.datetime(2025, 1, 2, 13, 0, tzinfo=UTC)) is False


def test_weekend_closed():
    # 2025-01-04 is a Saturday
    assert is_regular_session(dt.datetime(2025, 1, 4, 16, 0, tzinfo=UTC)) is False


def test_holiday_closed():
    # New Year's Day 2025
    assert is_regular_session(dt.datetime(2025, 1, 1, 16, 0, tzinfo=UTC)) is False


def test_session_dates_exclude_holiday_and_weekend():
    dates = regular_session_dates(dt.date(2025, 1, 1), dt.date(2025, 1, 7))
    assert dt.date(2025, 1, 1) not in dates  # holiday
    assert dt.date(2025, 1, 4) not in dates  # saturday
    assert dt.date(2025, 1, 2) in dates
