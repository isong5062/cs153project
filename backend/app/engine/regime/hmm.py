"""Hidden Markov regime model.

Fitting uses hmmlearn (Gaussian HMM, diagonal covariance) with BIC model
selection. Inference uses an explicit forward (filtering) pass implemented here,
so a prediction at time t depends only on observations up to t — no look-ahead.
The fitted parameters are fully serializable (JSON), so live inference never
needs an hmmlearn model object.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.special import logsumexp

from app.engine.features.engineering import REGIME_FEATURES

CANONICAL_LABELS = ["crash", "bear", "neutral", "bull", "euphoria"]

# Label sets matching the source video, keyed by regime count.
LABELS_BY_K = {
    3: ["bear", "neutral", "bull"],
    4: ["crash", "bear", "bull", "euphoria"],
    5: ["crash", "bear", "neutral", "bull", "euphoria"],
}


def label_states(state_means: dict[int, float], k: int) -> dict[int, str]:
    """Map HMM state indices to regime labels, ordered by mean return."""
    order = sorted(state_means, key=lambda s: state_means[s])  # ascending mean return
    labels = LABELS_BY_K.get(k)
    if labels is None:  # k outside 3..5 — bucket into the 5 canonical labels
        labels = [CANONICAL_LABELS[min(4, round(i / (k - 1) * 4))] for i in range(k)]
    return {state: labels[rank] for rank, state in enumerate(order)}


@dataclass
class RegimeModelParams:
    feature_cols: list[str]
    startprob: list[float]
    transmat: list[list[float]]
    means: list[list[float]]
    variances: list[list[float]]
    scaler_mean: list[float]
    scaler_scale: list[float]
    state_labels: list[str]
    n_components: int
    score: float  # best BIC

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RegimeModelParams:
        return cls(**d)


def _emission_loglik(xs: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """Per-state diagonal-Gaussian log-likelihood. xs scaled (T,D)."""
    t_n, k_n = xs.shape[0], means.shape[0]
    out = np.empty((t_n, k_n))
    for k in range(k_n):
        diff = xs - means[k]
        out[:, k] = -0.5 * np.sum(
            (diff * diff) / variances[k] + np.log(2.0 * np.pi * variances[k]), axis=1
        )
    return out


def _forward_filter(
    framelogprob: np.ndarray, startprob: np.ndarray, transmat: np.ndarray
) -> np.ndarray:
    """Filtered (forward-only) state posteriors. Row t uses observations <= t."""
    t_n, k_n = framelogprob.shape
    log_start = np.log(startprob + 1e-300)
    log_trans = np.log(transmat + 1e-300)
    log_alpha = np.empty((t_n, k_n))
    log_alpha[0] = log_start + framelogprob[0]
    for t in range(1, t_n):
        log_alpha[t] = framelogprob[t] + logsumexp(log_alpha[t - 1][:, None] + log_trans, axis=0)
    return np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))


def _bic(model, X: np.ndarray) -> float:
    try:
        return float(model.bic(X))
    except Exception:
        loglik = model.score(X)
        n, d = X.shape
        k = model.n_components
        n_params = (k - 1) + k * (k - 1) + k * d + k * d
        return float(-2 * loglik + n_params * np.log(n))


def fit_regime_model(
    features: pd.DataFrame,
    feature_cols: list[str] | None = None,
    k_min: int = 3,
    k_max: int = 5,
    random_state: int = 42,
) -> RegimeModelParams:
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    feature_cols = feature_cols or REGIME_FEATURES
    feats = features[feature_cols].dropna()
    if len(feats) < 10 * (k_min + 1):
        raise ValueError("not enough feature rows to fit a regime model")
    k_max = max(k_min, min(k_max, len(feats) // 10 - 1))

    scaler = StandardScaler()
    X = scaler.fit_transform(feats.values)

    best: tuple[float, int, object] | None = None
    for k in range(k_min, k_max + 1):
        try:
            model = GaussianHMM(
                n_components=k, covariance_type="diag", n_iter=100, random_state=random_state
            )
            model.fit(X)
            bic = _bic(model, X)
        except Exception:
            continue
        if best is None or bic < best[0]:
            best = (bic, k, model)
    if best is None:
        raise RuntimeError("HMM fit failed for all candidate regime counts")

    bic, k, model = best
    variances = np.array([np.diagonal(c) for c in model.covars_])
    states = model.predict(X)
    raw_ret = features.loc[feats.index, "log_return"].to_numpy()
    state_means = {
        s: (float(np.nanmean(raw_ret[states == s])) if np.any(states == s) else 0.0)
        for s in range(k)
    }
    labels_map = label_states(state_means, k)

    return RegimeModelParams(
        feature_cols=list(feature_cols),
        startprob=model.startprob_.tolist(),
        transmat=model.transmat_.tolist(),
        means=model.means_.tolist(),
        variances=variances.tolist(),
        scaler_mean=scaler.mean_.tolist(),
        scaler_scale=scaler.scale_.tolist(),
        state_labels=[labels_map[s] for s in range(k)],
        n_components=k,
        score=bic,
    )


def filtered_regimes(params: RegimeModelParams, features: pd.DataFrame) -> pd.DataFrame:
    """Online (no-look-ahead) regime label + confidence per bar."""
    feats = features[params.feature_cols].dropna()
    if feats.empty:
        return pd.DataFrame(columns=["state", "label", "confidence"])
    mean = np.asarray(params.scaler_mean)
    scale = np.asarray(params.scaler_scale)
    xs = (feats.values - mean) / scale
    framelogprob = _emission_loglik(xs, np.asarray(params.means), np.asarray(params.variances))
    filtered = _forward_filter(
        framelogprob, np.asarray(params.startprob), np.asarray(params.transmat)
    )
    states = filtered.argmax(axis=1)
    return pd.DataFrame(
        {
            "state": states,
            "label": [params.state_labels[s] for s in states],
            "confidence": filtered.max(axis=1),
        },
        index=feats.index,
    )
