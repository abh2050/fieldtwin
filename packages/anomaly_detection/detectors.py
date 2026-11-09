"""The compared methods, simplest first. Parameters are fixed in advance and are not tuned."""

from __future__ import annotations

import warnings
from typing import Protocol, Self

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import columns_of

PARAMETERS: dict[str, dict] = {
    "static_threshold": {"limit_quantiles": [0.005, 0.995]},
    "rolling_deviation": {"statistic": "max sensor z against a preceding causal baseline"},
    "logistic_regression": {
        "C": 1.0,
        "class_weight": "balanced",
        "max_iter": 5000,
        "convergence": "required",
    },
    "isolation_forest": {"n_estimators": 200, "max_samples": 4096},
    "hist_gradient_boosting": {
        "max_iter": 150,
        "learning_rate": 0.1,
        "max_leaf_nodes": 31,
        "l2_regularization": 1.0,
        "class_weight": "balanced",
    },
}


class Detector(Protocol):
    name: str
    history_windows: int

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self: ...
    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray: ...
    def predict_class(self, features: np.ndarray) -> np.ndarray | None: ...


def _max_ignoring_nan(values: np.ndarray) -> np.ndarray:
    output = np.full(values.shape[0], np.nan)
    any_value = ~np.isnan(values).all(axis=1)
    output[any_value] = np.nanmax(values[any_value], axis=1)
    return output


class StaticThreshold:
    """One fixed band per sensor, from training normal windows, as an alarm-limit list would be.

    3W publishes no alarm limits, so these come from data and are engineering-style, not engineered.
    """

    name = "static_threshold"
    history_windows = 1

    def __init__(self, names: list[str]):
        self.mean_columns = columns_of(names, "mean")

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        means = features[y == 0][:, self.mean_columns].astype(float)
        low, median, high = np.nanquantile(means, [0.005, 0.5, 0.995], axis=0)
        self.median = median
        spread = (high - low) / 2.0
        self.scale = np.where(spread > 0, spread, np.nan)
        return self

    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray:
        means = features[:, self.mean_columns].astype(float)
        return _max_ignoring_nan(np.abs(means - self.median) / self.scale)

    def predict_class(self, features: np.ndarray) -> None:
        return None


class RollingDeviation:
    """Largest sensor deviation from that same series' own recent past. No label is used."""

    name = "rolling_deviation"

    def __init__(self, names: list[str], baseline_windows: int, gap_windows: int):
        self.mean_columns = columns_of(names, "mean")
        self.std_columns = columns_of(names, "std")
        self.baseline, self.gap = baseline_windows, gap_windows
        self.history_windows = baseline_windows + gap_windows + 1

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        normal = features[y == 0].astype(float)
        noise = (
            np.nanmedian(normal[:, self.std_columns], axis=0)
            if len(normal)
            else np.zeros(len(self.std_columns))
        )
        level = (
            np.abs(np.nanmedian(normal[:, self.mean_columns], axis=0))
            if len(normal)
            else np.zeros(len(self.mean_columns))
        )
        # A floor for flat sensors, so a tiny change can't produce an unbounded score.
        self.floor = np.maximum(np.nan_to_num(noise), 1e-3 * np.nan_to_num(level)) + 1e-9
        return self

    def _sequence(self, means: np.ndarray) -> np.ndarray:
        frame = pd.DataFrame(means)
        rolling = frame.rolling(self.baseline, min_periods=max(self.baseline // 2, 2))
        center = rolling.mean().shift(self.gap).to_numpy()
        spread = rolling.std(ddof=0).shift(self.gap).to_numpy()
        return _max_ignoring_nan(
            np.abs(means - center) / np.maximum(np.nan_to_num(spread), self.floor)
        )

    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray:
        means = features[:, self.mean_columns].astype(float)
        output = np.full(len(features), np.nan)
        for value in pd.unique(seq):
            chosen = np.flatnonzero(seq == value)
            output[chosen] = self._sequence(means[chosen])
        return output

    def predict_class(self, features: np.ndarray) -> None:
        return None


class FitDidNotConverge(RuntimeError):
    """An iterative fit stopped at its limit. Its result isn't the model the method describes."""


# All six fits in Gate 5 converge within 640 iterations. The limit leaves wide room, and reaching it
# is an error, not a silent result.
MAX_ITERATIONS = 5000


class _Classifier:
    history_windows = 1
    model: object
    normal_index: int

    def _normal_probability(self, features: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(features)[:, self.normal_index]  # type: ignore[attr-defined]

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        self.model.fit(features, y)  # type: ignore[attr-defined]
        self.classes_ = self.model.classes_  # type: ignore[attr-defined]
        self.normal_index = int(np.flatnonzero(self.classes_ == 0)[0])
        return self

    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray:
        """-log P(normal). Same order as 1 - P(normal), without losing resolution when P is tiny.

        1 - P(normal) rounds to exactly 1.0 once P falls below about 1e-16, which ties many windows.
        """
        return -self._log_normal_probability(features)

    def _log_normal_probability(self, features: np.ndarray) -> np.ndarray:
        """log P(normal) from the raw decision values, so it stays finite however small P is.

        Taking the log of `predict_proba` doesn't work: probabilities below about 1e-308 become exactly
        0, and their log is minus infinity, which ties those windows again.
        """
        decision = self.model.decision_function(features)  # type: ignore[attr-defined]
        raw: np.ndarray = np.asarray(decision, dtype=float)
        if raw.ndim == 1:  # Two classes: the value is the log-odds of the second class.
            raw = np.column_stack([np.zeros_like(raw), raw])
        return raw[:, self.normal_index] - logsumexp(raw, axis=1)

    def predict_class(self, features: np.ndarray) -> np.ndarray:
        return self.model.predict(features)  # type: ignore[attr-defined]


class Logistic(_Classifier):
    """Interpretable linear classifier. Imputation and scaling are fitted inside `fit` only."""

    name = "logistic_regression"

    def __init__(self, seed: int, max_iter: int = MAX_ITERATIONS):
        self.model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                C=1.0, class_weight="balanced", max_iter=max_iter, random_state=seed
            ),
        )
        self.seed = seed
        self.max_iter = max_iter

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        """Fit, and refuse a result that stopped at the iteration limit instead of converging."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            super().fit(features, y, seq)
        iterations = int(np.max(self.model[-1].n_iter_))  # type: ignore[index]
        warned = any(issubclass(w.category, ConvergenceWarning) for w in caught)
        self.fit_report = {
            "iterations": iterations,
            "max_iter": self.max_iter,
            "converged": not warned and iterations < self.max_iter,
        }
        if not self.fit_report["converged"]:
            raise FitDidNotConverge(
                f"logistic regression stopped at {iterations} of {self.max_iter} iterations"
            )
        return self


class GradientBoosting(_Classifier):
    """Handles missing values natively, so nothing is imputed."""

    name = "hist_gradient_boosting"

    def __init__(self, seed: int):
        self.model = HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.1,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            class_weight="balanced",
            early_stopping=False,
            random_state=seed,
        )

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        # A sensor with no reading anywhere in training gives this model nothing to bin.
        self.keep = ~np.isnan(features).all(axis=0)
        return super().fit(features[:, self.keep], y, seq)

    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray:
        return super().score(features[:, self.keep], seq)

    def predict_class(self, features: np.ndarray) -> np.ndarray:
        return super().predict_class(features[:, self.keep])


class Isolation:
    """Fitted on training windows labeled normal. Event labels are never used."""

    name = "isolation_forest"
    history_windows = 1

    def __init__(self, seed: int):
        self.seed = seed

    def fit(self, features: np.ndarray, y: np.ndarray, seq: np.ndarray) -> Self:
        normal = features[y == 0]
        self.imputer = SimpleImputer(strategy="median", keep_empty_features=True).fit(normal)
        self.model = IsolationForest(
            n_estimators=200, max_samples=min(4096, len(normal)), random_state=self.seed, n_jobs=1
        ).fit(self.imputer.transform(normal))
        return self

    def score(self, features: np.ndarray, seq: np.ndarray) -> np.ndarray:
        return -self.model.score_samples(self.imputer.transform(features))

    def predict_class(self, features: np.ndarray) -> None:
        return None


def make_detector(
    name: str, names: list[str], *, seed: int, baseline_windows: int, gap_windows: int
) -> Detector:
    if name == "static_threshold":
        return StaticThreshold(names)
    if name == "rolling_deviation":
        return RollingDeviation(names, baseline_windows, gap_windows)
    if name == "logistic_regression":
        return Logistic(seed)
    if name == "isolation_forest":
        return Isolation(seed)
    if name == "hist_gradient_boosting":
        return GradientBoosting(seed)
    raise ValueError(f"unknown method {name}")


def training_rows(y: np.ndarray, *, cap_per_class: int, seed: int) -> np.ndarray:
    """Labeled rows capped per class by a fixed draw. Rows with y < 0 can't be chosen."""
    rng = np.random.default_rng(seed)
    chosen = []
    for label in np.unique(y[y >= 0]):
        rows = np.flatnonzero(y == label)
        if rows.size > cap_per_class:
            rows = np.sort(rng.choice(rows, cap_per_class, replace=False))
        chosen.append(rows)
    return np.concatenate(chosen)
