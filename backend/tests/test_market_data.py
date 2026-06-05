import datetime as dt

import pytest

from app.engine.data.service import MarketDataService
from app.engine.features.engineering import validate_bars
from tests.factories import FakeBarSource, make_ohlcv


def test_store_load_round_trip(db_session):
    df = make_ohlcv(n=60, seed=1)
    svc = MarketDataService(db_session, FakeBarSource({("SPY", "1Day"): df}))

    assert svc.fetch_and_store("SPY", "1Day", df.index[0], df.index[-1]) == 60
    # idempotent — storing the same range adds nothing
    assert svc.fetch_and_store("SPY", "1Day", df.index[0], df.index[-1]) == 0

    loaded = svc.load_bars("SPY", "1Day")
    assert len(loaded) == 60
    validate_bars(loaded)
    assert loaded["close"].iloc[-1] == pytest.approx(df["close"].iloc[-1], rel=1e-9)


def test_compute_and_store_features(db_session):
    df = make_ohlcv(n=120, seed=2)
    svc = MarketDataService(db_session, FakeBarSource({("SPY", "1Day"): df}))
    svc.fetch_and_store("SPY", "1Day", df.index[0], df.index[-1])

    assert svc.compute_and_store_features("SPY", "1Day") == 120
    feats = svc.load_features("SPY", "1Day")
    assert len(feats) == 120
    assert "log_return" in feats.columns


def test_upsert_bar_insert_then_update(db_session):
    svc = MarketDataService(db_session, None)
    ts = dt.datetime(2024, 1, 2, 15, 0, 0)

    assert svc.upsert_bar("AAPL", "5Min", ts, 1.0, 2.0, 0.5, 1.5, 100) is True
    assert svc.upsert_bar("AAPL", "5Min", ts, 1.0, 3.0, 0.5, 2.5, 200) is False  # update

    loaded = svc.load_bars("AAPL", "5Min")
    assert len(loaded) == 1
    assert loaded["high"].iloc[0] == 3.0
