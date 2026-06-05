import json

from app.engine.features.engineering import compute_features
from app.engine.learning.budget import LearningBudget
from app.engine.learning.feedback import propose_from_performance
from app.engine.learning.llm import LLMProposer
from app.engine.learning.service import ProposalService
from app.engine.strategies.service import StrategyService
from app.models.proposal import ProposalSource, ProposalStatus
from app.services.users import get_or_create_default_user
from tests.factories import default_spec, make_ohlcv

BT_KW = {"in_sample": 100, "out_sample": 70, "k_min": 3, "k_max": 3}


# --- fake Anthropic client ---
class _Block:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage(120, 60)


class _Messages:
    def __init__(self, payload):
        self._payload = payload

    def create(self, **kwargs):
        return _Resp(self._payload)


class FakeAnthropic:
    def __init__(self, spec_dict, rationale="bump neutral exposure"):
        self.messages = _Messages(json.dumps({"rationale": rationale, "spec": spec_dict}))


def _fake_llm():
    proposed = default_spec(mode="self_learning")
    proposed.regime_rules["neutral"].target_exposure = 0.7
    return LLMProposer(client=FakeAnthropic(proposed.model_dump(mode="json")))


def _data(n=240, seed=4):
    df = make_ohlcv(n=n, seed=seed)
    return df["close"], compute_features(df)


# --- #2 feedback ---
def test_feedback_reduces_loser_grows_winner():
    spec = default_spec()
    breakdown = {
        "bear": {"mean_return": -0.01, "n": 20},
        "bull": {"mean_return": 0.002, "n": 20},
    }
    out = propose_from_performance(spec, breakdown)
    assert out is not None
    assert out.regime_rules["bear"].target_exposure == 0.15  # 0.25 - 0.10
    assert out.regime_rules["bull"].target_exposure == 1.05  # 0.95 + 0.10


def test_feedback_no_change_returns_none():
    spec = default_spec()
    assert propose_from_performance(spec, {}) is None


# --- #4 LLM (fake client) ---
def test_llm_proposer_parses_and_validates():
    spec = default_spec(mode="self_learning")
    draft = _fake_llm().propose(spec, {"metrics": {}})
    assert draft.proposed_spec.regime_rules["neutral"].target_exposure == 0.7
    assert draft.input_tokens == 120


# --- ProposalService ---
def _self_learning_strategy(db):
    user = get_or_create_default_user(db)
    return StrategyService(db).create_strategy(user.id, "SL", default_spec(mode="self_learning"))


def test_manual_strategy_generates_no_proposals(db_session):
    user = get_or_create_default_user(db_session)
    strat = StrategyService(db_session).create_strategy(user.id, "M", default_spec(mode="manual"))
    prices, feats = _data()
    svc = ProposalService(db_session, llm=_fake_llm(), backtest_kwargs=BT_KW)
    assert svc.generate_for_strategy(strat, prices, feats) == []


def test_generate_creates_pending_proposals_with_backtest(db_session):
    strat = _self_learning_strategy(db_session)
    original_version = strat.current_version_id
    prices, feats = _data()
    svc = ProposalService(db_session, llm=_fake_llm(), backtest_kwargs=BT_KW)

    proposals = svc.generate_for_strategy(strat, prices, feats)
    assert len(proposals) >= 1
    assert all(p.status == ProposalStatus.pending and p.backtest_id is not None for p in proposals)
    assert any(p.source == ProposalSource.llm for p in proposals)
    # nothing auto-applied
    db_session.refresh(strat)
    assert strat.current_version_id == original_version


def test_budget_zero_pauses_llm(db_session):
    strat = _self_learning_strategy(db_session)
    prices, feats = _data()
    svc = ProposalService(
        db_session,
        llm=_fake_llm(),
        budget=LearningBudget(daily_token_budget=0),
        backtest_kwargs=BT_KW,
    )
    proposals = svc.generate_for_strategy(strat, prices, feats)
    assert all(p.source != ProposalSource.llm for p in proposals)  # LLM paused


def test_approve_creates_new_version(db_session):
    strat = _self_learning_strategy(db_session)
    original_version = strat.current_version_id
    prices, feats = _data()
    svc = ProposalService(db_session, llm=_fake_llm(), backtest_kwargs=BT_KW)
    proposals = svc.generate_for_strategy(strat, prices, feats)

    version = svc.approve(proposals[0].id)
    db_session.refresh(strat)
    assert strat.current_version_id == version.id
    assert strat.current_version_id != original_version
    assert proposals[0].status == ProposalStatus.approved
