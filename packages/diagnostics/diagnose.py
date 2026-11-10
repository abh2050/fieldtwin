"""Bayesian inversion of the network model for one gathering-line restriction.

Inputs are only what the preregistration allows: permanent-sensor telemetry with gaps, the
planned-operations calendar, the network design, and readings of measurements this module asks for.

Hypotheses are "no restriction" and every pipe at every severity on a grid. Each is solved with the
network model at the case's operating point: well deliverability calibrated from an early healthy
window, suction pressure as measured now. Its predicted sensor averages are compared with the
measured ones, with sensor noise estimated from the data plus a model-error term per sensor kind.
"""

from __future__ import annotations

import warnings
import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .forward import Forward, Sensor, calibrate_wells, sensors

HYPOTHESIS_NONE = "NONE"


@dataclass(frozen=True)
class MethodConfig:
    name: str = "M2_calibrated_inversion"
    calibrate_wells: bool = True
    baseline_hours: float = 6.0
    current_hours: float = 2.0
    severity_step: float = 0.01
    severity_max: float = 0.69
    prior_none: float = 0.15
    model_error: dict[str, float] = field(
        default_factory=lambda: {"PRESSURE": 0.0, "DP": 0.0, "FLOW": 0.0}
    )
    temperature: float = 1.0
    support_mass: float = 0.999
    support_cap: int = 120
    shut_in_support_cap: int = 40
    eig_draws: int = 48
    seed: int = 20261112


@dataclass(frozen=True)
class Action:
    kind: str
    target: str


@dataclass(frozen=True)
class MeasurementSpec:
    kind: str
    targets: tuple[str, ...]
    noise: float | None  # None: permanent sensor noise, averaged over the duration
    duration_h: float
    burden: str


def measurement_menu(prereg: dict[str, Any]) -> dict[str, MeasurementSpec]:
    menu = {}
    for kind, spec in prereg["measurements"].items():
        if not isinstance(spec, dict) or "targets" not in spec:
            continue
        noise = spec.get("noise_std_pa", spec.get("noise_std_sm3_per_s"))
        menu[kind] = MeasurementSpec(
            kind, tuple(spec["targets"]), noise, spec["duration_h"], spec["burden"]
        )
    return menu


def valid_actions(menu: dict[str, MeasurementSpec], shut_in: frozenset[str]) -> list[Action]:
    """Every action except a well test or shut-in test on a well the calendar shows shut in."""
    return [
        Action(kind, target)
        for kind, spec in menu.items()
        for target in spec.targets
        if not (kind in ("WELL_TEST", "SHUT_IN_TEST") and target in shut_in)
    ]


@dataclass
class Diagnosis:
    method: str
    probabilities: dict[str, float]
    ranking: list[str]
    severity: dict[str, Any]  # for the top-ranked pipe: pipe, point, p10, p90, p2.5, p97.5
    impact: dict[str, float]  # sm3/s, marginal over every hypothesis
    evidence: dict[str, dict[str, Any]]
    recommendation: dict[str, Any] | None
    calibration: dict[str, Any]
    # Internal state for updating after a measurement.
    grid: list[tuple[str | None, float]] = field(repr=False, default_factory=list)
    weights: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))
    impacts: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))


def _window_mean(frame: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    values = frame[columns].to_numpy(dtype=float)
    counts = np.sum(np.isfinite(values), axis=0)
    # A sensor with no valid sample in the window gives NaN, and is then left out of the likelihood.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        means = np.nanmean(values, axis=0) if len(values) else np.full(len(columns), np.nan)
    return means, counts


def _noise_scale(frame: pd.DataFrame, chosen: list[Sensor]) -> float:
    """The case's noise multiplier, estimated from sample spread in a steady window."""
    ratios = []
    for sensor in chosen:
        values = frame[sensor.tag].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if len(values) >= 12 and sensor.kind != "FLOW":
            ratios.append(np.std(values, ddof=1) / sensor.noise)
    return float(np.median(ratios)) if ratios else 1.0


def _shut_in_at(calendar: dict[str, Any], offset: int) -> frozenset[str]:
    return frozenset(
        op["asset_id"]
        for op in calendar.get("planned_operations", [])
        if op["kind"] == "SHUT_IN_WELL" and op["start_s"] <= offset < op["end_s"]
    )


def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def _quantiles(values: np.ndarray, weights: np.ndarray, probs: list[float]) -> list[float]:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cumulative = np.cumsum(w) / w.sum()
    return [float(v[min(int(np.searchsorted(cumulative, p)), len(v) - 1)]) for p in probs]


class Diagnoser:
    def __init__(
        self,
        telemetry: pd.DataFrame,
        calendar: dict[str, Any],
        prereg: dict[str, Any],
        config: MethodConfig,
    ):
        self.config = config
        self.prereg = prereg
        diagnosis_time = int(prereg["inputs"]["diagnosis_time_s"])
        offsets = telemetry["offset_s"].to_numpy()
        self.now = int(offsets.max())
        baseline = telemetry[offsets < config.baseline_hours * 3600]
        current = telemetry[offsets > diagnosis_time - config.current_hours * 3600]
        self.shut_in = _shut_in_at(calendar, self.now)
        shut_early = (
            set().union(*[_shut_in_at(calendar, int(o)) for o in baseline["offset_s"]])
            if len(baseline)
            else set()
        )

        probe = Forward({}, 1.6e6)
        self.all_sensors = sensors(probe.config, probe.graph)
        self.noise_scale = _noise_scale(baseline, self.all_sensors)
        multipliers: dict[str, float] = {}
        if config.calibrate_wells:
            flows = {
                w.id: float(baseline[f"{w.id}.FT"].mean())
                for w in probe.design.wells
                if w.id not in shut_early
            }
            heads = {
                w.id: float(baseline[f"{w.id}.PT-WH"].mean())
                for w in probe.design.wells
                if w.id not in shut_early
            }
            multipliers = calibrate_wells(probe.design, flows, heads)
        suction_gauge = float(current["COMP-SUCTION.PT"].mean())
        self.forward = Forward(
            multipliers, suction_gauge + probe.config.ambient.pressure_pa_abs, self.shut_in
        )
        means, counts = _window_mean(current, [s.tag for s in self.all_sensors])
        usable = [
            i
            for i, s in enumerate(self.all_sensors)
            if counts[i] > 0 and np.isfinite(means[i]) and s.tag != "COMP-SUCTION.PT"
        ]
        self.sensors = [self.all_sensors[i] for i in usable]
        self.observed = means[usable]
        self.variance = np.array(
            [
                (s.noise * self.noise_scale) ** 2 / counts[i] + config.model_error[s.kind] ** 2
                for s, i in zip(self.sensors, usable, strict=True)
            ]
        )
        self.calibration = {
            "well_multipliers": multipliers,
            "noise_scale": self.noise_scale,
            "suction_gauge_pa": suction_gauge,
            "sensors_used": len(self.sensors),
            "shut_in_at_diagnosis": sorted(self.shut_in),
        }
        severities = np.round(
            np.arange(config.severity_step, config.severity_max + 1e-9, config.severity_step), 6
        )
        self.grid: list[tuple[str | None, float]] = [(None, 0.0)] + [
            (p, float(s)) for p in self.forward.pipes for s in severities
        ]
        prior = np.array(
            [config.prior_none]
            + [(1 - config.prior_none) / (len(self.forward.pipes) * len(severities))]
            * (len(self.grid) - 1)
        )
        none = self.forward.solve(None, 0.0)
        self.base_flow = none.total_flow
        predictions, impacts = [], []
        for pipe, severity in self.grid:
            solution = self.forward.solve(pipe, severity)
            predictions.append(self.forward.vector(solution, self.sensors))
            impacts.append(self.base_flow - solution.total_flow)
        self.predictions = np.array(predictions)
        self.impacts = np.array(impacts)
        loglik = -0.5 * (((self.observed - self.predictions) ** 2) / self.variance).sum(axis=1)
        self.log_prior = np.log(prior)
        self.loglik = loglik / config.temperature
        self.weights = self._normalize(self.log_prior + self.loglik)
        self.readings: list[tuple[Action, np.ndarray]] = []

    @staticmethod
    def _normalize(log_weights: np.ndarray) -> np.ndarray:
        shifted = np.exp(log_weights - log_weights.max())
        return shifted / shifted.sum()

    def pipe_probabilities(self, weights: np.ndarray) -> dict[str, float]:
        probs = {HYPOTHESIS_NONE: float(weights[0])}
        for (pipe, _), w in zip(self.grid[1:], weights[1:], strict=True):
            key = pipe or HYPOTHESIS_NONE
            probs[key] = probs.get(key, 0.0) + float(w)
        return probs

    def summarize(self, weights: np.ndarray, recommend: bool) -> Diagnosis:
        probs = self.pipe_probabilities(weights)
        ranking = sorted(probs, key=lambda h: -probs[h])
        top_pipe = next(h for h in ranking if h != HYPOTHESIS_NONE)
        fine_sev, fine_w, fine_impact = self._refine(top_pipe, weights)
        severity = {"pipe": top_pipe, "point": float((fine_sev * fine_w).sum() / fine_w.sum())}  # type: ignore[dict-item]
        q = _quantiles(fine_sev, fine_w, [0.1, 0.9, 0.025, 0.975])
        severity.update({"p10": q[0], "p90": q[1], "p2_5": q[2], "p97_5": q[3]})
        # Impact: the top pipe's refined distribution, mixed with every other hypothesis at its coarse weight.
        others = [i for i, (p, _) in enumerate(self.grid) if p != top_pipe]
        values = np.concatenate([fine_impact, self.impacts[others]])
        mass = np.concatenate([fine_w / fine_w.sum() * probs[top_pipe], weights[others]])
        qi = _quantiles(values, mass, [0.5, 0.1, 0.9, 0.025, 0.975])
        impact = {"point": qi[0], "p10": qi[1], "p90": qi[2], "p2_5": qi[3], "p97_5": qi[4]}
        evidence = {h: self._evidence(h, weights) for h in ranking[:3]}
        recommendation = self._recommend(weights) if recommend else None
        return Diagnosis(
            self.config.name,
            probs,
            ranking,
            severity,
            impact,
            evidence,
            recommendation,
            self.calibration,
            self.grid,
            weights,
            self.impacts,
        )

    def _loglik_at(self, pipe: str, severity: float) -> float:
        """Log-likelihood of every observation so far for one hypothesis, including measurement readings."""
        solution = self.forward.solve(pipe, severity)
        value = -0.5 * float(
            (
                ((self.observed - self.forward.vector(solution, self.sensors)) ** 2) / self.variance
            ).sum()
        )
        for action, reading in self.readings:
            pred, noise = self._predict_single(action, pipe, severity)
            value += -0.5 * float((((reading - pred) ** 2) / noise).sum())
        return value / self.config.temperature

    def _refine(self, pipe: str, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """A fine severity grid around the top pipe's mode, so intervals aren't limited by grid spacing."""
        rows = [i for i, (p, _) in enumerate(self.grid) if p == pipe]
        mode = self.grid[max(rows, key=lambda i: weights[i])][1]
        step = self.config.severity_step
        fine = np.round(
            np.arange(
                max(mode - 4 * step, 0.001),
                min(mode + 4 * step, self.config.severity_max) + 1e-9,
                step / 20,
            ),
            6,
        )
        loglik = np.array([self._loglik_at(pipe, float(s)) for s in fine])
        w = self._normalize(loglik)
        impact = np.array(
            [self.base_flow - self.forward.solve(pipe, float(s)).total_flow for s in fine]
        )
        return fine, w, impact

    def _predict_single(
        self, action: Action, pipe: str | None, severity: float
    ) -> tuple[np.ndarray, np.ndarray]:
        index = len(self.grid)
        self.grid.append((pipe, severity))
        try:
            pred, noise = self.predict_action(action, np.array([index]))
        finally:
            self.grid.pop()
        return pred[0], noise

    def _best_row(self, hypothesis: str, weights: np.ndarray) -> int:
        if hypothesis == HYPOTHESIS_NONE:
            return 0
        rows = [i for i, (p, _) in enumerate(self.grid) if p == hypothesis]
        return max(rows, key=lambda i: weights[i])

    def _evidence(self, hypothesis: str, weights: np.ndarray) -> dict[str, Any]:
        """Sensors that favour this hypothesis over its strongest rival, and those that count against it."""
        mine = self._best_row(hypothesis, weights)
        probs = self.pipe_probabilities(weights)
        rival_h = max((h for h in probs if h != hypothesis), key=lambda h: probs[h])
        rival = self._best_row(rival_h, weights)
        r_mine = (self.observed - self.predictions[mine]) ** 2 / self.variance
        r_rival = (self.observed - self.predictions[rival]) ** 2 / self.variance
        contribution = 0.5 * (r_rival - r_mine)
        order = np.argsort(-contribution)
        sd = np.sqrt(self.variance)

        def item(i: int) -> dict[str, Any]:
            return {
                "sensor": self.sensors[i].tag,
                "log_likelihood_ratio": round(float(contribution[i]), 3),
                "residual_sd_this": round(
                    float((self.observed[i] - self.predictions[mine][i]) / sd[i]), 2
                ),
                "residual_sd_rival": round(
                    float((self.observed[i] - self.predictions[rival][i]) / sd[i]), 2
                ),
            }

        return {
            "against": rival_h,
            "for": [item(i) for i in order[:3] if contribution[i] > 0],
            "against_items": [item(i) for i in order[::-1][:3] if contribution[i] < 0],
        }

    # Measurements

    def _support(self, weights: np.ndarray, cap: int) -> np.ndarray:
        order = np.argsort(-weights)
        cumulative = np.cumsum(weights[order])
        count = min(int(np.searchsorted(cumulative, self.config.support_mass)) + 1, cap)
        return order[:count]

    def predict_action(self, action: Action, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predicted readings for the given hypotheses, and the reading noise variance."""
        menu = measurement_menu(self.prereg)
        spec = menu[action.kind]
        if action.kind == "SHUT_IN_TEST":
            samples = spec.duration_h * 12
            noise = np.array(
                [
                    (s.noise * self.noise_scale) ** 2 / samples
                    + self.config.model_error[s.kind] ** 2
                    for s in self.sensors
                ]
            )
            pred = np.array(
                [
                    self.forward.vector(
                        self.forward.solve(
                            self.grid[i][0], self.grid[i][1], extra_shut_in=action.target
                        ),
                        self.sensors,
                    )
                    for i in rows
                ]
            )
            return pred, noise
        kind = {"PORTABLE_DP": "DP", "PRECISION_PT": "PRESSURE", "WELL_TEST": "FLOW"}[action.kind]
        assert spec.noise is not None
        noise = np.array([spec.noise**2 + self.config.model_error[kind] ** 2])
        values = []
        for i in rows:
            solution = self.forward.solve(*self.grid[i])
            if action.kind == "PORTABLE_DP":
                values.append([self.forward.pipe_dp(solution, action.target)])
            elif action.kind == "PRECISION_PT":
                values.append([solution.pressure_pa_abs[action.target] - self.forward.ambient])
            else:
                values.append([solution.edge_flow_sm3_per_s[f"INFLOW:{action.target}"]])
        return np.array(values), noise

    def _pipe_entropy(self, rows: np.ndarray, weights: np.ndarray) -> float:
        totals: dict[str, float] = {}
        for i, w in zip(rows, weights, strict=True):
            key = self.grid[i][0] or HYPOTHESIS_NONE
            totals[key] = totals.get(key, 0.0) + float(w)
        return _entropy(np.array(list(totals.values())) / sum(totals.values()))

    def expected_gain(self, action: Action, weights: np.ndarray) -> float:
        cap = (
            self.config.shut_in_support_cap
            if action.kind == "SHUT_IN_TEST"
            else self.config.support_cap
        )
        rows = self._support(weights, cap)
        w = weights[rows] / weights[rows].sum()
        pred, noise = self.predict_action(action, rows)
        rng = np.random.default_rng(
            [self.config.seed, zlib.crc32(f"{action.kind}:{action.target}".encode())]
        )
        before = self._pipe_entropy(rows, w)
        after = 0.0
        draws = rng.choice(len(rows), size=self.config.eig_draws, p=w)
        for k in draws:
            y = pred[k] + rng.normal(0.0, np.sqrt(noise))
            log_post = (
                np.log(w) - 0.5 * (((y - pred) ** 2) / noise).sum(axis=1) / self.config.temperature
            )
            after += self._pipe_entropy(rows, self._normalize(log_post))
        return before - after / len(draws)

    def _recommend(self, weights: np.ndarray) -> dict[str, Any]:
        menu = measurement_menu(self.prereg)
        scored = [(self.expected_gain(a, weights), a) for a in valid_actions(menu, self.shut_in)]
        gain, best = max(scored, key=lambda pair: (pair[0], -menu[pair[1].kind].duration_h))
        spec = menu[best.kind]
        return {
            "kind": best.kind,
            "target": best.target,
            "expected_entropy_reduction_nats": round(gain, 4),
            "duration_h": spec.duration_h,
            "burden": spec.burden,
            "rationale": f"Of {len(scored)} valid actions, this one is expected to reduce uncertainty about the faulted pipe the most.",
        }

    def update(self, action: Action, reading: np.ndarray) -> Diagnosis:
        """Fold in one measurement's reading and summarize again, with no further recommendation."""
        rows = np.flatnonzero(self.weights > self.weights.max() * 1e-9)
        pred, noise = self.predict_action(action, rows)
        log_post = np.full(len(self.weights), -np.inf)
        log_post[rows] = (
            np.log(self.weights[rows])
            - 0.5
            * (((np.asarray(reading) - pred) ** 2) / noise).sum(axis=1)
            / self.config.temperature
        )
        self.readings.append((action, np.asarray(reading)))
        try:
            return self.summarize(self._normalize(log_post), recommend=False)
        finally:
            self.readings.pop()


def load_method(path) -> MethodConfig:
    """The frozen method configuration (config/diagnostics/d1_method.yaml)."""
    import yaml

    data = yaml.safe_load(open(path).read())
    return MethodConfig(**data)


def diagnose(
    telemetry: pd.DataFrame,
    calendar: dict[str, Any],
    prereg: dict[str, Any],
    config: MethodConfig,
    recommend: bool = True,
) -> tuple[Diagnosis, Diagnoser]:
    diagnoser = Diagnoser(telemetry, calendar, prereg, config)
    return diagnoser.summarize(diagnoser.weights, recommend), diagnoser


def hypothesis_entropy(probabilities: dict[str, float]) -> float:
    return _entropy(np.array(list(probabilities.values())))


__all__ = [
    "Action",
    "Diagnosis",
    "Diagnoser",
    "MethodConfig",
    "diagnose",
    "hypothesis_entropy",
    "load_method",
]
