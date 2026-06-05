"""Populate the local DB with demo content so every page has something to show.

Offline-friendly. Seeds the SPY regime (if missing) + synthetic bars for a small
universe, creates a manual and a self-learning strategy, runs a few orchestrator
ticks (producing equity snapshots + sim trades), and generates a pending
self-learning proposal so the Approvals inbox is testable. Uses real Claude when
``ANTHROPIC_API_KEY`` is set, otherwise a built-in fake proposer so the whole
approval flow works with no keys.

Run from ``backend/``::

    python -m app.demo
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.engine.data.service import MarketDataService
from app.engine.features.engineering import compute_features
from app.engine.learning.llm import LLMProposer
from app.engine.learning.service import ProposalService
from app.engine.loop.orchestrator import Orchestrator
from app.engine.regime.service import RegimeService
from app.engine.strategies.service import StrategyService
from app.engine.strategies.spec import RegimeRule, StrategySpec
from app.models.strategy import StrategyStatus
from app.seed import seed_regime, synthetic_spy
from app.services.users import get_or_create_default_user

logger = logging.getLogger("demo")

BT_KW = {"in_sample": 100, "out_sample": 70, "k_min": 3, "k_max": 3}
UNIVERSE = ["AAPL", "MSFT"]


def _demo_spec(mode: str, universe: list[str]) -> StrategySpec:
    return StrategySpec(
        mode=mode,
        universe=list(universe),
        regime_rules={
            "crash": RegimeRule(target_exposure=0.0, max_leverage=1.0),
            "bear": RegimeRule(target_exposure=0.25, max_leverage=1.0),
            "neutral": RegimeRule(target_exposure=0.5, max_leverage=1.0),
            "bull": RegimeRule(target_exposure=0.95, max_leverage=1.25),
            "euphoria": RegimeRule(target_exposure=0.6, max_leverage=1.0),
        },
    )


def _fake_llm() -> LLMProposer:
    """A fake Anthropic client so the proposal flow works without an API key."""
    proposed = _demo_spec("self_learning", UNIVERSE)
    proposed.regime_rules["neutral"].target_exposure = 0.7
    payload = json.dumps(
        {
            "rationale": "Demo proposal: raise neutral-regime exposure 0.50 -> 0.70 "
            "based on the backtest's per-regime returns.",
            "spec": proposed.model_dump(mode="json"),
        }
    )

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text
            self.type = "text"

    class _Usage:
        input_tokens = 100
        output_tokens = 50

    class _Resp:
        content = [_Block(payload)]
        usage = _Usage()

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    return LLMProposer(client=_Client())


def run_demo(db: Session) -> dict:
    if RegimeService(db).latest_regime("SPY") is None:
        seed_regime(db)

    user = get_or_create_default_user(db)
    strategies = StrategyService(db)

    # Synthetic 5-minute bars for the universe so price maps + features resolve.
    mds = MarketDataService(db)
    price_map: dict[str, float] = {}
    for i, sym in enumerate(UNIVERSE):
        bars = synthetic_spy(days=300, seed=20 + i)
        mds.store_bars(sym, "5Min", bars)
        price_map[sym] = float(bars["close"].iloc[-1])

    manual = strategies.create_strategy(user.id, "Demo Manual", _demo_spec("manual", UNIVERSE))
    manual.status = StrategyStatus.simulated
    sl = strategies.create_strategy(
        user.id, "Demo Self-Learning", _demo_spec("self_learning", UNIVERSE)
    )
    sl.status = StrategyStatus.simulated
    db.commit()

    # A few ticks produce equity snapshots + sim trades for the performance views.
    orch = Orchestrator(db)
    base = dt.datetime(2025, 1, 2, 15, 0, tzinfo=dt.UTC)
    for k in range(3):
        orch.run_tick(base + dt.timedelta(minutes=5 * k), price_map, force=True)

    # One pending self-learning proposal so the Approvals inbox has content.
    settings = get_settings()
    llm = LLMProposer() if settings.anthropic_api_key else _fake_llm()
    df = synthetic_spy(days=240, seed=99)
    proposals = ProposalService(db, llm=llm, backtest_kwargs=BT_KW).generate_for_strategy(
        sl, df["close"], compute_features(df)
    )

    summary = {
        "manual_strategy_id": manual.id,
        "self_learning_strategy_id": sl.id,
        "pending_proposals": len(proposals),
        "universe": UNIVERSE,
    }
    logger.info("demo populated: %s", summary)
    return summary


def main() -> None:
    setup_logging()
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        print(run_demo(db))


if __name__ == "__main__":
    main()
