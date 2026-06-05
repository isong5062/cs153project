"""RegimeService: fit/store a regime model and detect/store per-bar regimes."""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.engine.regime.hmm import RegimeModelParams, filtered_regimes, fit_regime_model
from app.engine.regime.stability import StabilityFilter
from app.models.regime import Regime, RegimeModel


class RegimeService:
    def __init__(self, db: Session, stability: StabilityFilter | None = None) -> None:
        self._db = db
        self._stability = stability or StabilityFilter()

    def fit_and_store(self, symbol: str, features: pd.DataFrame) -> RegimeModel:
        params = fit_regime_model(features)
        row = RegimeModel(
            symbol=symbol,
            n_components=params.n_components,
            score=params.score,
            params=params.to_dict(),
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def load_params(self, model_row: RegimeModel) -> RegimeModelParams:
        return RegimeModelParams.from_dict(model_row.params)

    def latest_model(self, symbol: str) -> RegimeModel | None:
        return (
            self._db.query(RegimeModel)
            .filter_by(symbol=symbol)
            .order_by(RegimeModel.trained_at.desc(), RegimeModel.id.desc())
            .first()
        )

    def detect_and_store(self, symbol: str, features: pd.DataFrame, model_row: RegimeModel) -> int:
        params = self.load_params(model_row)
        df = filtered_regimes(params, features)
        if df.empty:
            return 0
        stable, flags = self._stability.apply(df["label"].tolist())
        ts_list = [t.to_pydatetime() for t in pd.DatetimeIndex(df.index)]
        existing = {
            r[0]
            for r in self._db.query(Regime.ts)
            .filter(Regime.symbol == symbol, Regime.ts.in_(ts_list))
            .all()
        }
        rows = []
        for ts, label, conf, unstable in zip(
            ts_list, stable, df["confidence"].tolist(), flags, strict=True
        ):
            if ts in existing:
                continue
            rows.append(
                Regime(
                    symbol=symbol,
                    ts=ts,
                    label=label,
                    confidence=float(conf),
                    unstable=bool(unstable),
                    model_id=model_row.id,
                )
            )
        if rows:
            self._db.add_all(rows)
            self._db.commit()
        return len(rows)

    def latest_regime(self, symbol: str) -> Regime | None:
        return (
            self._db.query(Regime)
            .filter_by(symbol=symbol)
            .order_by(Regime.ts.desc())
            .first()
        )
