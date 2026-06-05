import pytest
from pydantic import ValidationError

from app.engine.strategies.evaluator import evaluate
from app.engine.strategies.service import StrategyService
from app.engine.strategies.spec import Condition, ConditionGroup, RegimeRule, StrategySpec
from app.models.strategy import CreatedBy, StrategyStatus
from app.services.users import get_or_create_default_user
from tests.factories import default_spec


def test_spec_valid_and_normalized():
    spec = default_spec(universe=["aapl", "msft", "aapl"])
    assert spec.universe == ["AAPL", "MSFT"]  # uppercased + de-duplicated


def test_spec_rejects_unknown_regime():
    with pytest.raises(ValidationError):
        StrategySpec(universe=["AAPL"], regime_rules={"sideways": RegimeRule(target_exposure=0.5)})


def test_spec_rejects_empty_universe():
    with pytest.raises(ValidationError):
        StrategySpec(universe=[], regime_rules={"bull": RegimeRule(target_exposure=0.5)})


def test_spec_rejects_out_of_range_exposure():
    with pytest.raises(ValidationError):
        RegimeRule(target_exposure=10.0)


def test_evaluator_equal_weight_and_flat():
    spec = default_spec(universe=["AAPL", "MSFT"])
    w = evaluate(spec, "bull", {"AAPL": {}, "MSFT": {}})
    assert w["AAPL"] == pytest.approx(0.475)  # min(0.95, 1.25) / 2
    assert w["MSFT"] == pytest.approx(0.475)

    assert evaluate(spec, "crash", {"AAPL": {}, "MSFT": {}}) == {"AAPL": 0.0, "MSFT": 0.0}
    assert evaluate(spec, "sideways", {}) == {"AAPL": 0.0, "MSFT": 0.0}  # unknown regime -> flat


def test_evaluator_entry_condition_filters():
    rule = RegimeRule(
        target_exposure=1.0,
        entry=ConditionGroup(conditions=[Condition(indicator="rsi_14", op="<", value=30)]),
    )
    spec = StrategySpec(universe=["AAPL", "MSFT"], regime_rules={"bull": rule})
    feats = {"AAPL": {"rsi_14": 25.0}, "MSFT": {"rsi_14": 55.0}}
    w = evaluate(spec, "bull", feats)
    assert w["AAPL"] == pytest.approx(1.0)  # only AAPL passes -> full exposure
    assert w["MSFT"] == 0.0


def test_evaluator_unstable_scaling():
    spec = default_spec(universe=["AAPL"])
    base = evaluate(spec, "bull", {"AAPL": {}})["AAPL"]
    reduced = evaluate(spec, "bull", {"AAPL": {}}, unstable=True)["AAPL"]
    assert reduced == pytest.approx(base * 0.5)


def test_strategy_create_and_versioning(db_session):
    user = get_or_create_default_user(db_session)
    svc = StrategyService(db_session)

    strat = svc.create_strategy(user.id, "My Strategy", default_spec())
    assert strat.current_version_id is not None
    assert strat.status == StrategyStatus.draft

    v2 = svc.update_spec(strat.id, default_spec(universe=["TSLA"]), created_by=CreatedBy.user)
    assert v2.version_num == 2
    db_session.refresh(strat)
    assert strat.current_version_id == v2.id

    spec = svc.current_spec(strat)
    assert spec.universe == ["TSLA"]
    assert len(svc.list_versions(strat.id)) == 2
