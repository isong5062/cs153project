"""Background trading worker: runs the orchestrator tick on a schedule.

Run with:  python -m app.worker   (or via docker-compose).
Operates only on stored bars + the latest regime; it is paper-only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger("worker")


def build_price_map(db, symbols: list[str], timeframe: str = "5Min") -> dict[str, float]:
    from app.engine.data.service import MarketDataService

    svc = MarketDataService(db)
    out: dict[str, float] = {}
    for s in symbols:
        bars = svc.load_bars(s, timeframe)
        if not bars.empty:
            out[s] = float(bars["close"].iloc[-1])
    return out


def run_once() -> dict:
    from app.db.session import SessionLocal
    from app.engine.loop.orchestrator import Orchestrator

    with SessionLocal() as db:
        orch = Orchestrator(db)
        symbols: set[str] = set()
        for strat in orch.active_strategies():
            spec = orch._strategies.current_spec(strat)
            if spec:
                symbols.update(spec.universe)
        price_map = build_price_map(db, sorted(symbols))
        result = orch.run_tick(datetime.now(UTC), price_map)
        logger.info("tick result: %s", result)
        return result


def main() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    from app.core.logging import setup_logging

    setup_logging()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_once, "interval", minutes=5, id="tick", max_instances=1)
    logger.info("worker started (5-minute tick)")
    scheduler.start()


if __name__ == "__main__":
    main()
