from types import SimpleNamespace

import pytest

from app.engine.execution.alpaca import AlpacaExecutor
from app.engine.execution.router import ExecutionRouter
from app.engine.execution.simulator import SimulatedExecutor
from app.engine.strategies.service import StrategyService
from app.models.execution import OrderStatus
from app.models.strategy import StrategyStatus
from app.services.users import get_or_create_default_user
from tests.factories import default_spec


# --- Simulated executor ---
def test_sim_buy_updates_position_and_cash(db_session):
    ex = SimulatedExecutor(db_session, slippage_bps=0.0, initial_cash=100_000)
    ex.submit(1, "NVDA", "buy", 10, price=100.0)
    pos = ex.positions(1)
    assert pos["NVDA"].qty == 10
    assert pos["NVDA"].avg_price == pytest.approx(100.0)
    assert ex.equity(1, {"NVDA": 100.0}) == pytest.approx(100_000.0)


def test_sim_slippage_and_flatten(db_session):
    ex = SimulatedExecutor(db_session, slippage_bps=10.0, initial_cash=100_000)  # 10 bps
    ex.submit(1, "NVDA", "buy", 10, price=100.0)  # fills at 100.10
    assert ex.equity(1, {"NVDA": 100.0}) == pytest.approx(99_999.0)
    ex.flatten(1, {"NVDA": 100.0})  # sells at 99.90
    assert ex.positions(1) == {}
    assert ex.equity(1, {"NVDA": 100.0}) == pytest.approx(99_998.0)


# --- Paper lock + Alpaca round-trip (mocked client) ---
class _FakeBrokerOrder:
    def __init__(self, oid):
        self.id = oid


class _FakeTradingClient:
    def __init__(self):
        self.submitted = []
        self.closed = False

    def submit_order(self, req):
        self.submitted.append(req)
        return _FakeBrokerOrder("abc123")

    def close_all_positions(self, cancel_orders=True):
        self.closed = True

    def get_all_positions(self):
        return []


def test_paper_lock_blocks_live(db_session):
    settings = SimpleNamespace(alpaca_paper=False, alpaca_api_key="k", alpaca_secret_key="s")
    with pytest.raises(RuntimeError):
        AlpacaExecutor(settings, db_session, client=_FakeTradingClient())


def test_alpaca_paper_round_trip(db_session):
    settings = SimpleNamespace(alpaca_paper=True, alpaca_api_key="k", alpaca_secret_key="s")
    fake = _FakeTradingClient()
    ex = AlpacaExecutor(settings, db_session, client=fake)
    order = ex.submit(1, "NVDA", "buy", 10)
    assert order.status == OrderStatus.submitted
    assert order.broker_order_id == "abc123"
    assert order.executor == "alpaca"
    assert len(fake.submitted) == 1


# --- Router: one live, rest sim; promotion flattens + rebinds ---
class _FakeAlpacaExec:
    name = "alpaca"

    def __init__(self):
        self.flattened = []

    def flatten(self, strategy_id, prices=None):
        self.flattened.append(strategy_id)


def test_router_promote_flattens_and_rebinds(db_session):
    user = get_or_create_default_user(db_session)
    svc = StrategyService(db_session)
    a = svc.create_strategy(user.id, "A", default_spec())
    b = svc.create_strategy(user.id, "B", default_spec())
    a.status = StrategyStatus.live
    db_session.commit()

    sim = SimulatedExecutor(db_session)
    alpaca = _FakeAlpacaExec()
    router = ExecutionRouter(db_session, sim, alpaca)

    assert router.live_strategy().id == a.id
    router.promote(b.id)

    db_session.refresh(a)
    db_session.refresh(b)
    assert a.status == StrategyStatus.simulated
    assert b.status == StrategyStatus.live
    assert alpaca.flattened == [a.id]  # outgoing live was flattened
