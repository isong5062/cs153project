import numpy as np
import pandas as pd
import pytest

from app.engine.features.engineering import compute_features
from app.engine.regime.hmm import RegimeModelParams, filtered_regimes, label_states
from app.engine.regime.service import RegimeService
from app.engine.regime.stability import StabilityFilter
from tests.factories import make_ohlcv


def test_label_states_ordering():
    labels = label_states({0: 0.5, 1: -0.5, 2: 0.0}, 3)
    assert labels[1] == "bear"
    assert labels[2] == "neutral"
    assert labels[0] == "bull"

    l4 = label_states({0: -0.9, 1: -0.1, 2: 0.1, 3: 0.9}, 4)
    assert l4[0] == "crash"
    assert l4[3] == "euphoria"


def _toy_params() -> RegimeModelParams:
    return RegimeModelParams(
        feature_cols=["x"],
        startprob=[0.5, 0.5],
        transmat=[[0.9, 0.1], [0.1, 0.9]],
        means=[[0.0], [5.0]],
        variances=[[1.0], [1.0]],
        scaler_mean=[0.0],
        scaler_scale=[1.0],
        state_labels=["bear", "bull"],
        n_components=2,
        score=0.0,
    )


def test_filtered_no_lookahead():
    """Filtering on a prefix equals the full series' value at that point."""
    params = _toy_params()
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(0, 1, 30), rng.normal(5, 1, 30)])
    feats = pd.DataFrame({"x": x}, index=pd.date_range("2023-01-02", periods=60, freq="B"))

    full = filtered_regimes(params, feats)
    for k in (10, 25, 45, 60):
        part = filtered_regimes(params, feats.iloc[:k])
        assert part["confidence"].iloc[-1] == pytest.approx(
            full["confidence"].iloc[k - 1], abs=1e-9
        )
        assert part["label"].iloc[-1] == full["label"].iloc[k - 1]


def test_stability_filter_persistence_and_flicker():
    sf = StabilityFilter(min_persistence=3, flicker_window=20, flicker_threshold=4)
    labels = ["bull"] * 5 + ["bear", "bull", "bear", "bull", "bear"] + ["bear"] * 5
    stable, flags = sf.apply(labels)

    assert stable[4] == "bull"
    assert stable[5] == "bull"  # a single 'bear' must not switch the stable regime
    assert stable[-1] == "bear"  # 3+ consecutive 'bear' eventually switches
    assert any(flags)  # flicker zone flagged


def test_fit_and_detect_integration(db_session):
    feats = compute_features(make_ohlcv(n=400, seed=3))
    svc = RegimeService(db_session)

    model = svc.fit_and_store("SPY", feats)
    assert 3 <= model.n_components <= 5

    assert svc.detect_and_store("SPY", feats, model) > 0
    latest = svc.latest_regime("SPY")
    assert latest is not None
    assert latest.label in {"crash", "bear", "neutral", "bull", "euphoria"}
    assert 0.0 <= latest.confidence <= 1.0
