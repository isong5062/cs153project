"""Tournament harness (plan §9.2).

Runs every registered strategy through walk-forward, layers on Monte Carlo, and
ranks by a composite score:

    composite = 0.4 * z(Sharpe) + 0.2 * z(Calmar) + 0.2 * z(-MaxDD)
              + 0.1 * z(-Turnover) + 0.1 * z(TailRatio)

Where ``z()`` is the leaderboard-local z-score so the weighting is scale-free.
Missing metrics default to 0 after z-scoring (neutral).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.backtest.montecarlo import MonteCarloResult, monte_carlo_returns
from src.backtest.vectorbt_runner import BacktestConfig
from src.backtest.walkforward import WalkForwardResult, walk_forward
from src.signals.strategies.base import BaseStrategy


@dataclass
class TournamentEntry:
    strategy_name: str
    strategy_version: str
    wf: WalkForwardResult
    mc: MonteCarloResult
    composite: float = 0.0


@dataclass
class TournamentResult:
    entries: list[TournamentEntry] = field(default_factory=list)

    def leaderboard(self) -> pd.DataFrame:
        rows = []
        for e in self.entries:
            s = e.wf.oos_stats
            rows.append(
                {
                    "strategy": f"{e.strategy_name}@{e.strategy_version}",
                    "composite": e.composite,
                    "oos_sharpe": s.get("sharpe", 0.0),
                    "oos_calmar": s.get("calmar", 0.0),
                    "oos_max_dd": s.get("max_drawdown", 0.0),
                    "oos_total_return": s.get("total_return", 0.0),
                    "mc_dd_p05": e.mc.max_drawdown_p05,
                    "mc_sharpe_p05": e.mc.sharpe_p05,
                    "folds": len(e.wf.folds),
                }
            )
        df = pd.DataFrame(rows).sort_values("composite", ascending=False).reset_index(drop=True)
        return df


def _zscore(values: list[float]) -> list[float]:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return []
    mean = float(np.nanmean(arr))
    std = float(np.nanstd(arr, ddof=0))
    if std == 0 or np.isnan(std):
        return [0.0] * arr.size
    return [float(x) for x in ((arr - mean) / std).tolist()]


def _composite_scores(entries: list[TournamentEntry]) -> list[float]:
    sharpes = [e.wf.oos_stats.get("sharpe", 0.0) for e in entries]
    calmars = [e.wf.oos_stats.get("calmar", 0.0) for e in entries]
    neg_mdd = [-e.wf.oos_stats.get("max_drawdown", 0.0) for e in entries]
    mc_sharpe = [e.mc.sharpe_p05 for e in entries]
    # Turnover-proxy: number of trades (higher = more friction). Lower is better.
    turnover_proxy = [sum(f.test_result.num_trades for f in e.wf.folds) for e in entries]
    neg_turn: list[float] = [float(-t) for t in turnover_proxy]

    zs = _zscore(sharpes)
    zc = _zscore(calmars)
    zd = _zscore(neg_mdd)
    zm = _zscore(mc_sharpe)
    zt = _zscore(neg_turn)

    return [
        0.4 * zs[i] + 0.2 * zc[i] + 0.2 * zd[i] + 0.1 * zm[i] + 0.1 * zt[i]
        for i in range(len(entries))
    ]


def run_tournament(
    strategies: list[type[BaseStrategy]],
    bars: dict[str, pd.DataFrame],
    *,
    train_months: int = 12,
    test_months: int = 3,
    mc_sims: int = 5_000,
    config: BacktestConfig | None = None,
) -> TournamentResult:
    entries: list[TournamentEntry] = []
    for strat_cls in strategies:
        wf = walk_forward(
            strat_cls,
            bars,
            train_months=train_months,
            test_months=test_months,
            config=config,
        )
        mc = monte_carlo_returns(wf.oos_returns, n_sims=mc_sims)
        entries.append(
            TournamentEntry(
                strategy_name=strat_cls.name,
                strategy_version=strat_cls.version,
                wf=wf,
                mc=mc,
            )
        )

    scores = _composite_scores(entries)
    for e, s in zip(entries, scores, strict=True):
        e.composite = float(s)

    entries.sort(key=lambda x: x.composite, reverse=True)
    return TournamentResult(entries=entries)
