"""Live-trading metrics computed from the persisted equity curve and trades.

Backtests have their own metrics in ``src.backtest`` (vectorbt-driven).
This module is the live-side counterpart so the paper-trading week can be
graded against the same dimensions: Sharpe, max drawdown, hit rate, etc.
"""

from src.metrics.live import (
    LiveMetrics,
    compute_live_metrics,
    equity_to_returns,
)

__all__ = ["LiveMetrics", "compute_live_metrics", "equity_to_returns"]
