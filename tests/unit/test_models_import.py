"""Verify that the full ORM model graph loads without errors.

Catches relationship typos and circular-import regressions early.
"""

from __future__ import annotations


def test_all_models_register_with_base() -> None:
    from src.persistence.models import Base

    expected = {
        "bars",
        "strategies",
        "signals",
        "agent_runs",
        "trades",
        "equity_curve",
        "backtests",
        "reflections",
        "reflection_proposals",
    }
    tables = set(Base.metadata.tables)
    missing = expected - tables
    assert not missing, f"missing tables: {missing}"
