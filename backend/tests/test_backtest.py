import pandas as pd

from app.engine.backtest.service import BacktestService
from app.engine.backtest.walkforward import compute_walk_forward_exposure, run_walk_forward
from app.engine.features.engineering import compute_features
from tests.factories import default_spec, make_ohlcv


def _data(n: int = 360, seed: int = 5):
    df = make_ohlcv(n=n, seed=seed)
    return df["close"], compute_features(df)


def test_run_walk_forward_produces_reports():
    prices, feats = _data()
    res = run_walk_forward(
        prices, feats, default_spec(), in_sample=120, out_sample=60, k_min=3, k_max=4
    )
    assert res.n_windows >= 2
    assert set(res.metrics) >= {"total_return", "sharpe", "max_drawdown"}
    assert set(res.benchmarks) == {"buy_hold", "sma_200", "random"}
    assert "max_drawdown" in res.stress
    assert len(res.equity_curve) > 0


def test_walk_forward_no_leakage():
    """Dropping the final OOS window must not change earlier windows' exposures."""
    prices, feats = _data(n=360)
    spec = default_spec()
    exp_full, *_ = compute_walk_forward_exposure(prices, feats, spec, 120, 60, 3, 4)
    exp_pre, *_ = compute_walk_forward_exposure(
        prices.iloc[:300], feats.iloc[:300], spec, 120, 60, 3, 4
    )
    common = exp_pre.index[120:]  # OOS region of the shortened series
    pd.testing.assert_series_equal(exp_full.loc[common], exp_pre.loc[common])


def test_backtest_service_stores(db_session):
    prices, feats = _data()
    bt = BacktestService(db_session).run_and_store(
        1, prices, feats, default_spec(), in_sample=120, out_sample=60, k_min=3, k_max=4
    )
    assert bt.id is not None
    assert "metrics" in bt.result
    assert "benchmarks" in bt.result
