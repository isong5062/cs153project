"""Hard paper-trading lock for v1 — no real-money code path may run."""

from __future__ import annotations

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def assert_paper_only(settings) -> None:
    if not getattr(settings, "alpaca_paper", True):
        raise RuntimeError(
            "v1 is paper-only: ALPACA_PAPER must be true (refusing to enable live trading)."
        )
