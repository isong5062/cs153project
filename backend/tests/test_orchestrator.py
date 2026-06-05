import datetime as dt

from app.engine.loop.orchestrator import Orchestrator
from app.engine.strategies.service import StrategyService
from app.models.strategy import StrategyStatus
from app.services.users import get_or_create_default_user
from tests.factories import default_spec

UTC = dt.UTC


def _make_sim_strategy(db, universe=("AAPL", "MSFT")):
    user = get_or_create_default_user(db)
    strat = StrategyService(db).create_strategy(user.id, "S", default_spec(universe=universe))
    strat.status = StrategyStatus.simulated
    db.commit()
    return strat


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_run_tick_places_orders(db_session):
    strat = _make_sim_strategy(db_session)
    orch = Orchestrator(db_session)
    now = dt.datetime(2025, 1, 2, 15, 0, tzinfo=UTC)

    res = orch.run_tick(
        now, {"AAPL": 100.0, "MSFT": 200.0}, regime=("bull", 0.9, False), force=True
    )
    info = res["strategies"][strat.id]
    assert info["orders"] > 0
    assert info["halted"] is False

    sim = orch._router.executor_for(strat)
    pos = sim.positions(strat.id)
    assert pos["AAPL"].qty > 0


def test_run_tick_skips_when_market_closed(db_session):
    _make_sim_strategy(db_session)
    orch = Orchestrator(db_session)
    saturday = dt.datetime(2025, 1, 4, 16, 0, tzinfo=UTC)
    res = orch.run_tick(saturday, {"AAPL": 100.0}, regime=("bull", 0.9, False), force=False)
    assert res["status"] == "skipped_market_closed"


def test_run_tick_isolates_strategy_errors(db_session, monkeypatch):
    strat = _make_sim_strategy(db_session)
    orch = Orchestrator(db_session)
    monkeypatch.setattr(orch._risk, "evaluate", _boom)
    now = dt.datetime(2025, 1, 2, 15, 0, tzinfo=UTC)

    res = orch.run_tick(
        now, {"AAPL": 100.0, "MSFT": 200.0}, regime=("bull", 0.9, False), force=True
    )
    assert "error" in res["strategies"][strat.id]  # captured, did not crash the tick


def test_drawdown_halts_and_flattens(db_session):
    strat = _make_sim_strategy(db_session)
    orch = Orchestrator(db_session)

    orch.run_tick(
        dt.datetime(2025, 1, 2, 15, 0, tzinfo=UTC),
        {"AAPL": 100.0, "MSFT": 200.0},
        regime=("bull", 0.9, False),
        force=True,
    )
    # ~20% crash on the next tick -> drawdown stop -> halt + flatten + block
    res = orch.run_tick(
        dt.datetime(2025, 1, 2, 15, 5, tzinfo=UTC),
        {"AAPL": 80.0, "MSFT": 160.0},
        regime=("bull", 0.9, False),
        force=True,
    )
    assert res["strategies"][strat.id]["halted"] is True
    assert orch._router.executor_for(strat).positions(strat.id) == {}
    assert orch._risk.is_blocked(strat.id)
