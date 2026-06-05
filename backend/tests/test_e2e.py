"""End-to-end: regime -> strategy -> orchestrated sim trade -> proposal -> approval.

Exercises the whole vision in-process with synthetic data and a fake LLM, so it
runs with no network, no API keys, and no external services.
"""

from datetime import UTC, datetime

from app.engine.features.engineering import compute_features
from app.engine.learning.service import ProposalService
from app.engine.loop.orchestrator import Orchestrator
from app.engine.regime.service import RegimeService
from app.engine.strategies.service import StrategyService
from app.models.proposal import ProposalSource, ProposalStatus
from app.models.strategy import StrategyStatus
from app.seed import synthetic_spy
from app.services.users import get_or_create_default_user
from tests.factories import default_spec, make_fake_llm, make_ohlcv

BT_KW = {"in_sample": 100, "out_sample": 70, "k_min": 3, "k_max": 3}


def test_full_vision_in_process(db_session):
    # 1. Seed a market-wide regime from a synthetic SPY series.
    spy = synthetic_spy(days=400, seed=11)
    spy_feats = compute_features(spy)
    rsvc = RegimeService(db_session)
    model = rsvc.fit_and_store("SPY", spy_feats)
    rsvc.detect_and_store("SPY", spy_feats, model)
    assert rsvc.latest_regime("SPY") is not None

    # 2. Create a self-learning strategy and move it into simulation.
    user = get_or_create_default_user(db_session)
    strat = StrategyService(db_session).create_strategy(
        user.id, "E2E", default_spec(mode="self_learning", universe=["AAPL", "MSFT"])
    )
    strat.status = StrategyStatus.simulated
    db_session.commit()

    # 3. One orchestrator tick trades the sim executor using the live DB regime.
    orch = Orchestrator(db_session)
    res = orch.run_tick(
        datetime(2025, 1, 2, 15, 0, tzinfo=UTC), {"AAPL": 100.0, "MSFT": 200.0}, force=True
    )
    assert strat.id in res["strategies"]
    assert "error" not in res["strategies"][strat.id]

    # 4. Self-learning proposes a change; nothing applies without approval.
    df = make_ohlcv(240, seed=4)
    prices, feats = df["close"], compute_features(df)
    svc = ProposalService(db_session, llm=make_fake_llm(), backtest_kwargs=BT_KW)
    proposals = svc.generate_for_strategy(strat, prices, feats)
    assert any(p.source == ProposalSource.llm for p in proposals)
    assert all(p.status == ProposalStatus.pending for p in proposals)

    original_version = strat.current_version_id

    # 5. Approving creates a new immutable version and deploys it.
    version = svc.approve(proposals[0].id)
    db_session.refresh(strat)
    assert strat.current_version_id == version.id
    assert strat.current_version_id != original_version


def test_manual_strategy_emits_no_proposals_end_to_end(db_session):
    user = get_or_create_default_user(db_session)
    strat = StrategyService(db_session).create_strategy(
        user.id, "Manual", default_spec(mode="manual")
    )
    df = make_ohlcv(240, seed=4)
    svc = ProposalService(db_session, llm=make_fake_llm(), backtest_kwargs=BT_KW)
    assert svc.generate_for_strategy(strat, df["close"], compute_features(df)) == []
