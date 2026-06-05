"""Bootstrap a regime model + detections so the dashboard shows a live regime.

Uses real Alpaca daily SPY bars when API keys are configured; otherwise falls
back to a regime-rich synthetic series so the full pipeline (and the dashboard)
work fully offline. Run from the ``backend/`` directory::

    python -m app.seed
"""

from __future__ import annotations

import datetime as dt
import logging

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.engine.features.engineering import compute_features
from app.engine.regime.service import RegimeService

logger = logging.getLogger("seed")


def synthetic_spy(days: int = 600, seed: int = 7) -> pd.DataFrame:
    """A regime-rich synthetic daily series: bull trend, drawdown shock, recovery."""
    rng = np.random.default_rng(seed)
    third = days // 3
    drift = np.concatenate(
        [
            np.full(third, 0.0006),  # bull
            np.full(third, -0.0013),  # bear / crash
            np.full(days - 2 * third, 0.0003),  # recovery / neutral
        ]
    )
    vol = np.concatenate(
        [
            np.full(third, 0.008),
            np.full(third, 0.021),
            np.full(days - 2 * third, 0.011),
        ]
    )
    rets = rng.normal(drift, vol)
    close = 400 * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.001, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, days)))
    volume = rng.integers(50_000_000, 120_000_000, days).astype(float)
    idx = pd.date_range(end=dt.date.today(), periods=days, freq="B", name="ts")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )


def _load_bars(db: Session, symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    """Real Alpaca daily bars when keys are present, else a synthetic series."""
    s = get_settings()
    if s.alpaca_api_key and s.alpaca_secret_key:
        from app.engine.data.service import MarketDataService

        svc = MarketDataService(db)
        end = dt.datetime.now(dt.UTC)
        start = end - dt.timedelta(days=days * 2)  # calendar -> ~days trading days
        svc.fetch_and_store(symbol, "1Day", start, end)
        return svc.load_bars(symbol, "1Day"), "alpaca"
    return synthetic_spy(days), "synthetic"


def seed_regime(db: Session, symbol: str = "SPY", days: int = 600) -> dict:
    """Fit + store a regime model and detect/store per-bar regimes for ``symbol``."""
    bars, source = _load_bars(db, symbol, days)
    if bars.empty:
        raise RuntimeError(f"no bars available to seed regime for {symbol}")
    features = compute_features(bars)
    rsvc = RegimeService(db)
    model = rsvc.fit_and_store(symbol, features)
    n = rsvc.detect_and_store(symbol, features, model)
    latest = rsvc.latest_regime(symbol)
    summary = {
        "symbol": symbol,
        "source": source,
        "bars": int(len(bars)),
        "regimes_stored": int(n),
        "n_components": int(model.n_components),
        "latest_label": latest.label if latest else None,
        "latest_confidence": round(latest.confidence, 4) if latest else None,
    }
    logger.info("seeded regime: %s", summary)
    return summary


def main() -> None:
    setup_logging()
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        print(seed_regime(db))


if __name__ == "__main__":
    main()
