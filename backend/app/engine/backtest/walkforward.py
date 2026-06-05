"""Walk-forward, allocation-based backtest.

For each rolling window the regime HMM is fit on the in-sample slice only, then
applied (online filtering) to the out-of-sample slice. Exposure for day t is
decided from the regime known at t-1 and applied to day t's return, so there is
no look-ahead. Benchmarks and crash stress tests are computed over the same OOS
region. The backtest measures the regime-timing edge against the regime asset.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from app.engine.performance.metrics import (
    equity_from_returns,
    max_drawdown,
    summarize,
    total_return,
)
from app.engine.regime.hmm import filtered_regimes, fit_regime_model
from app.engine.strategies.spec import StrategySpec


@dataclass
class BacktestResult:
    metrics: dict
    benchmarks: dict
    regime_breakdown: dict
    confidence_buckets: dict
    stress: dict
    n_windows: int
    equity_curve: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _exposure_for(spec: StrategySpec, label: str) -> float:
    rule = spec.regime_rules.get(label)
    return min(rule.target_exposure, rule.max_leverage) if rule else 0.0


def compute_walk_forward_exposure(
    prices: pd.Series,
    features: pd.DataFrame,
    spec: StrategySpec,
    in_sample: int = 252,
    out_sample: int = 126,
    k_min: int = 3,
    k_max: int = 5,
) -> tuple[pd.Series, pd.Series, pd.Series, int]:
    n = len(prices)
    exposure = pd.Series(0.0, index=prices.index)
    labels = pd.Series("", index=prices.index, dtype=object)
    conf = pd.Series(np.nan, index=prices.index)

    start = in_sample
    n_windows = 0
    while start < n:
        oos_end = min(start + out_sample, n)
        try:
            params = fit_regime_model(features.iloc[:start], k_min=k_min, k_max=k_max)
        except Exception:
            start = oos_end
            continue
        reg = filtered_regimes(params, features.iloc[:oos_end])
        for d in prices.index[start:oos_end]:
            if d in reg.index:
                lab = reg.at[d, "label"]
                exposure.at[d] = _exposure_for(spec, lab)
                labels.at[d] = lab
                conf.at[d] = reg.at[d, "confidence"]
        n_windows += 1
        start = oos_end

    return exposure, labels, conf, n_windows


def _confidence_buckets(sret: pd.Series, conf: pd.Series) -> dict:
    c = conf.dropna()
    if len(c) < 3:
        return {}
    q1, q2 = c.quantile([1 / 3, 2 / 3])
    out = {}
    masks = {"low": c <= q1, "mid": (c > q1) & (c <= q2), "high": c > q2}
    for name, m in masks.items():
        rr = sret.loc[c[m].index]
        out[name] = {"mean_return": float(rr.mean()) if len(rr) else 0.0, "n": int(len(rr))}
    return out


def _benchmarks(prices: pd.Series, oos_mask: pd.Series, slippage_bps: float) -> dict:
    returns = prices.pct_change().fillna(0.0)
    bh = summarize(returns[oos_mask])

    sma = prices.rolling(200).mean()
    sma_sig = (prices > sma).astype(float).shift(1).fillna(0.0)
    sma_ret = (sma_sig * returns)[oos_mask]

    rng = np.random.default_rng(0)
    rnd_sig = (
        pd.Series(rng.integers(0, 2, len(prices)), index=prices.index)
        .astype(float)
        .shift(1)
        .fillna(0.0)
    )
    rnd_ret = (rnd_sig * returns)[oos_mask]

    return {"buy_hold": bh, "sma_200": summarize(sma_ret), "random": summarize(rnd_ret)}


def stress_test(
    strat_returns: pd.Series, n_shocks: int = 3, shock: float = -0.12, seed: int = 0
) -> dict:
    if len(strat_returns) == 0:
        return {"max_drawdown": 0.0, "total_return": 0.0}
    r = strat_returns.copy()
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(r), size=min(n_shocks, len(r)), replace=False)
    r.iloc[idx] = r.iloc[idx] + shock
    eq = equity_from_returns(r)
    return {"max_drawdown": max_drawdown(eq), "total_return": total_return(eq)}


def run_walk_forward(
    prices: pd.Series,
    features: pd.DataFrame,
    spec: StrategySpec,
    in_sample: int = 252,
    out_sample: int = 126,
    slippage_bps: float = 5.0,
    k_min: int = 3,
    k_max: int = 5,
) -> BacktestResult:
    exposure, labels, conf, n_windows = compute_walk_forward_exposure(
        prices, features, spec, in_sample, out_sample, k_min, k_max
    )

    returns = prices.pct_change().fillna(0.0)
    prev_exp = exposure.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(0.0)
    strat_ret = prev_exp * returns - turnover * (slippage_bps / 1e4)

    oos_mask = prices.index >= prices.index[in_sample]
    sret = strat_ret[oos_mask]
    lab_oos = labels[oos_mask]

    breakdown = {}
    for lab in sorted(set(lab_oos) - {""}):
        rr = sret[lab_oos == lab]
        breakdown[lab] = {"mean_return": float(rr.mean()) if len(rr) else 0.0, "n": int(len(rr))}

    return BacktestResult(
        metrics=summarize(sret),
        benchmarks=_benchmarks(prices, oos_mask, slippage_bps),
        regime_breakdown=breakdown,
        confidence_buckets=_confidence_buckets(sret, conf[oos_mask]),
        stress=stress_test(sret),
        n_windows=n_windows,
        equity_curve=[float(x) for x in equity_from_returns(sret).tolist()],
    )
