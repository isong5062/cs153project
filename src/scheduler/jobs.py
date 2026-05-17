"""Scheduled jobs for the paper trading loop (plan §4.9).

Schedule (US Eastern, market-hour local time):
  09:25 — pre-market refresh: load universe, warm caches.
  09:31 — generate signals, size, guard, submit.
  every 15 min — manage stops / check circuit breakers.
  16:05 — end-of-day wrap: equity snapshot + reconcile.

This module only *wires* the jobs; the callables accept the collaborators they
need, so tests can pass fakes and exercise the full loop without APScheduler
firing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.broker.base import Broker
from src.execution.order_manager import OrderManager, OrderOutcome, SignalIntent
from src.logging import get_logger

log = get_logger(__name__)

SignalProducer = Callable[[], list[SignalIntent]]
EquitySink = Callable[[Decimal, Decimal], None]  # (equity, day_pnl)
OutcomeSink = Callable[[list[SignalIntent], list[OrderOutcome]], None]


@dataclass(slots=True)
class _EquityTracker:
    """Minimal in-memory high-water mark + session anchor.

    Persistence to ``equity_curve`` happens via the EquitySink callback
    supplied by whatever wires this up (typically a repo).
    """

    peak: Decimal = Decimal("0")
    day_start: Decimal = Decimal("0")

    def on_session_open(self, equity: Decimal) -> None:
        self.day_start = equity
        if equity > self.peak:
            self.peak = equity

    def on_tick(self, equity: Decimal) -> None:
        if equity > self.peak:
            self.peak = equity


class TradingScheduler:
    """Owns the APScheduler instance and the set of registered jobs.

    Timezone: APScheduler handles cron in the tz we pass. US/Eastern matches
    market local time; use ``pendulum`` tz strings to avoid DST foot-guns.
    """

    def __init__(
        self,
        *,
        broker: Broker,
        order_manager: OrderManager,
        produce_signals: SignalProducer,
        record_equity: EquitySink | None = None,
        record_outcomes: OutcomeSink | None = None,
        timezone: str = "US/Eastern",
    ) -> None:
        self._broker = broker
        self._om = order_manager
        self._produce = produce_signals
        self._record_equity = record_equity
        self._record_outcomes = record_outcomes
        self._tz = timezone
        self._tracker = _EquityTracker()
        self._scheduler = BackgroundScheduler(timezone=timezone)

    def register_jobs(self) -> None:
        self._scheduler.add_job(
            self.pre_market,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=25, timezone=self._tz),
            id="pre_market",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.generate_and_submit,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=31, timezone=self._tz),
            id="generate_and_submit",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.manage_intraday,
            IntervalTrigger(minutes=15),
            id="manage_intraday",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.end_of_day,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=self._tz),
            id="end_of_day",
            replace_existing=True,
        )

    def start(self) -> None:
        self.register_jobs()
        self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)

    # ── jobs ───────────────────────────────────────────────────────────────

    def pre_market(self) -> None:
        acct = self._broker.get_account()
        self._tracker.on_session_open(acct.equity)
        log.info(
            "pre_market",
            equity=str(acct.equity),
            cash=str(acct.cash),
            peak=str(self._tracker.peak),
        )

    def generate_and_submit(self) -> None:
        intents = self._produce()
        if not intents:
            log.info("generate_and_submit.empty")
            return
        outcomes = self._om.process(
            intents,
            peak_equity=self._tracker.peak,
            day_start_equity=self._tracker.day_start,
        )
        submitted = sum(1 for o in outcomes if o.submitted)
        log.info(
            "generate_and_submit",
            total=len(outcomes),
            submitted=submitted,
            rejected=len(outcomes) - submitted,
        )
        if self._record_outcomes:
            entry_intents = [i for i in intents if i.is_entry or i.is_exit]
            self._record_outcomes(entry_intents, outcomes)

    def manage_intraday(self) -> None:
        acct = self._broker.get_account()
        self._tracker.on_tick(acct.equity)
        day_pnl = acct.equity - self._tracker.day_start
        if self._record_equity:
            self._record_equity(acct.equity, day_pnl)

    def end_of_day(self) -> None:
        acct = self._broker.get_account()
        self._tracker.on_tick(acct.equity)
        day_pnl = acct.equity - self._tracker.day_start
        log.info(
            "end_of_day",
            ts=datetime.now(UTC).isoformat(),
            equity=str(acct.equity),
            day_pnl=str(day_pnl),
            peak=str(self._tracker.peak),
        )
        if self._record_equity:
            self._record_equity(acct.equity, day_pnl)


def build_scheduler(
    broker: Broker,
    order_manager: OrderManager,
    produce_signals: SignalProducer,
    *,
    record_equity: EquitySink | None = None,
    record_outcomes: OutcomeSink | None = None,
    timezone: str = "US/Eastern",
) -> TradingScheduler:
    return TradingScheduler(
        broker=broker,
        order_manager=order_manager,
        produce_signals=produce_signals,
        record_equity=record_equity,
        record_outcomes=record_outcomes,
        timezone=timezone,
    )
