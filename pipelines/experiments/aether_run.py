"""The AETHER synthetic benchmark. Everything here is SYNTHETIC. Detection delay is simulation time."""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from packages.anomaly_detection.contracts import InputDomain
from packages.anomaly_detection.evaluation import (
    ClusterCounts,
    episode_starts,
    score_windows,
    select_preferred,
)
from packages.anomaly_detection.features import columns_of
from packages.anomaly_detection.inference import ModelBundle, save_bundle
from packages.scenario_engine.benchmark_runs import load_design
from packages.scenario_engine.field_simulation import GOOD, default_setup, simulate_by_id
from pipelines.experiments import tracking
from pipelines.experiments.aether_data import features_of, load_track, rule_for
from pipelines.experiments.common import (
    MODELS,
    PARAMETERS,
    Fitted,
    Track,
    confusion,
    evaluate_rows,
    fit_and_calibrate,
    git_sha,
    hardware,
    read_result,
    report_counts,
    scores_sha256,
    write_result,
)
from pipelines.experiments.three_w_audit import evaluation_config

CLASS_NAMES = {0: "NORMAL", 1: "RESTRICTION", 2: "DERATE", 3: "SENSOR"}
PERTURBATIONS = ("sensors_25pct_removed", "rows_20pct_missing", "ten_percent_of_time_lost")


def _fit_all(config: dict, track: Track) -> dict[str, Fitted]:
    settings = config["aether"]
    split = track.table["split"].to_numpy()
    train, validation = np.flatnonzero(split == "train"), np.flatnonzero(split == "validation")
    return {
        m: fit_and_calibrate(m, track, train, validation, config, settings)
        for m in config["methods"]
    }


def _delays(counts: ClusterCounts) -> dict:
    """Simulation-time delay. The model is quasi-steady, so this isn't a physical detection latency."""
    output = {}
    for label, group in counts.events.groupby("event_class"):
        hours = group["delay_s"].dropna() / 3600.0
        if len(hours):
            output[CLASS_NAMES[int(label)]] = {
                "detected": len(hours),
                "median_hours": float(hours.median()),
                "q25_hours": float(hours.quantile(0.25)),
                "q75_hours": float(hours.quantile(0.75)),
            }
    return output


def _alarm_context(track: Track, rows: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    """Where false alarms start, because normal operations also move the telemetry."""
    frame = track.table.iloc[rows].reset_index(drop=True)
    rule = rule_for()
    counts = {"during_planned_work": 0, "during_dropout": 0, "other_normal_operation": 0}
    hours = {
        "during_planned_work": 0.0,
        "during_dropout": 0.0,
        "other_normal_operation": 0.0,
    }
    normal = frame["y"] == 0
    hours["during_planned_work"] = (
        float((normal & frame["planned_active"]).sum()) * rule.stride_s / 3600
    )
    hours["during_dropout"] = float((normal & frame["dropout_active"]).sum()) * rule.stride_s / 3600
    hours["other_normal_operation"] = (
        float((normal & ~frame["planned_active"] & ~frame["dropout_active"]).sum())
        * rule.stride_s
        / 3600
    )
    for _, index in frame.groupby("seq", sort=False).indices.items():
        starts, _ = episode_starts(scores[index], frame["t"].to_numpy()[index], threshold, rule)
        for start in starts:
            row = frame.iloc[index[start]]
            if row["y"] != 0:
                continue
            if row["planned_active"]:
                counts["during_planned_work"] += 1
            elif row["dropout_active"]:
                counts["during_dropout"] += 1
            else:
                counts["other_normal_operation"] += 1
    return {"false_alarms": counts, "hours": hours}


def _evaluate(fitted: Fitted, track: Track, rows: np.ndarray, config: dict) -> dict:
    counts, scores, precision = evaluate_rows(fitted, track, rows, rule_for())
    result = report_counts(counts, config)
    result |= {
        "average_precision": precision,
        "delays": _delays(counts),
        "alarm_context": _alarm_context(track, rows, scores, fitted.threshold),
        "scores_sha256": scores_sha256(scores),
        "by_category": _by_category(track, rows, counts),
    }
    return result


def _by_category(track: Track, rows: np.ndarray, counts: ClusterCounts) -> dict:
    category = track.table.iloc[rows].groupby("seq")["category"].first()
    events = counts.events.assign(category=counts.events["seq"].map(category))
    output = {}
    for name, group in events.groupby("category"):
        output[name] = {"events": len(group), "detected": int(group["detected"].sum())}
    return output


def in_regime() -> None:
    config = evaluation_config()
    track, _ = load_track()
    fitted = _fit_all(config, track)
    rows = np.flatnonzero(track.table["split"].to_numpy() == "test")
    methods = {}
    for name, model in fitted.items():
        methods[name] = _evaluate(model, track, rows, config) | {
            "threshold": model.threshold,
            "calibration": model.calibration,
            "fit_seconds": model.fit_seconds,
            "training_rows": model.training_rows,
            "confusion": confusion(model, track, rows, list(CLASS_NAMES)),
        }
        s = methods[name]["summary"]
        print(
            name,
            "recall",
            s["event_recall"],
            "FA/h",
            round(s["false_alarms_per_hour"], 4),
            "P",
            s["precision"],
            "R",
            s["recall"],
            flush=True,
        )
    table = [
        {
            "method": m,
            "event_skill": r["summary"]["event_skill"] or 0.0,
            "false_alarms_per_hour": r["summary"]["false_alarms_per_hour"],
            "time_in_alarm": r["summary"]["time_in_alarm"],
            "interval": r["interval"],
        }
        for m, r in methods.items()
    ]
    selection = select_preferred(
        table,
        order=config["methods"],
        budget=config["alarm"]["false_alarms_per_hour_budget"],
        max_time_in_alarm=config["alarm"]["max_fraction_of_normal_time_in_alarm"],
    )
    write_result(
        "aether_in_regime",
        {
            "track": "SYNTHETIC experiment: uncalibrated fictional AETHER model",
            "git_sha": git_sha(),
            "dataset": read_result("aether_dataset"),
            "methods": methods,
            "selection": selection,
            "hardware": hardware(),
        },
    )
    print(selection)


def _perturbed_features(track_rows_table: pd.DataFrame, kind: str, seed: int, spec) -> np.ndarray:
    from pipelines.experiments.aether_data import TELEMETRY

    parts = []
    for index, case_id in enumerate(pd.unique(track_rows_table["seq"])):
        telemetry = pd.read_parquet(TELEMETRY / f"{case_id}.parquet")
        values = telemetry[list(spec.sensors)].to_numpy(dtype=float, copy=True)
        rng = np.random.default_rng(
            np.random.SeedSequence([seed, index, PERTURBATIONS.index(kind)])
        )
        if kind == "sensors_25pct_removed":
            values[:, rng.choice(values.shape[1], values.shape[1] // 4, replace=False)] = np.nan
        elif kind == "rows_20pct_missing":
            values[rng.random(values.shape) < 0.2] = np.nan
        else:
            values[np.arange(len(values)) % 120 < 12] = np.nan
        telemetry = telemetry.copy()
        telemetry[list(spec.sensors)] = values
        parts.append(features_of(telemetry, spec)[0])
    return np.concatenate(parts)


def _gate4_anchors(config: dict, fitted: dict[str, Fitted], spec) -> dict:
    """The six accepted Gate 4 scenarios, unmodified. A reference only: one seed and fixed parameters."""
    catalog = default_setup()[3]
    rule = rule_for()
    output = {}
    for scenario in catalog.scenarios:
        run = simulate_by_id(scenario.scenario_id)
        long = run.telemetry
        wide = (
            long.assign(value=long["value"].where(long["quality"] == GOOD))
            .pivot(index="offset_s", columns="tag", values="value")
            .reset_index()
        )
        features, offsets = features_of(wide, spec)
        onset = None
        if scenario.category.value in ("PHYSICAL_FAULT", "SENSOR_FAULT"):
            onset = scenario.first_onset_s
        results: dict = {}
        row: dict = {"category": scenario.category.value, "onset_s": onset, "methods": results}
        for name, model in fitted.items():
            scores = model.detector.score(features, np.zeros(len(features), dtype=np.int64))
            starts, _ = episode_starts(scores, offsets, model.threshold, rule)
            alarm_times = offsets[starts]
            before = int((alarm_times < onset).sum()) if onset is not None else len(alarm_times)
            inside = alarm_times[alarm_times >= onset] if onset is not None else np.array([])
            results[name] = {
                "alarms_before_onset_or_without_fault": before,
                "detected": bool(inside.size) if onset is not None else None,
                "delay_hours_simulation_time": float((inside[0] - onset) / 3600)
                if inside.size
                else None,
            }
        output[scenario.scenario_id] = row
    return output


def held_out() -> None:
    config = evaluation_config()
    track, spec = load_track()
    fitted = _fit_all(config, track)
    table = track.table
    split = table["split"].to_numpy()
    regimes = {}
    for regime in load_design()["held_out_regimes"]:
        rows = np.flatnonzero((split == "held_out") & (table["regime"].to_numpy() == regime))
        regimes[regime] = {
            name: _evaluate(model, track, rows, config) for name, model in fitted.items()
        }
        print(
            regime,
            {
                n: (
                    r["summary"]["events_detected"],
                    r["summary"]["events"],
                    round(r["summary"]["false_alarms_per_hour"], 3),
                )
                for n, r in regimes[regime].items()
            },
            flush=True,
        )
    rows = np.flatnonzero(split == "held_out")
    pooled = {name: _evaluate(model, track, rows, config) for name, model in fitted.items()}

    test = np.flatnonzero(split == "test")
    robustness: dict = {}
    frame = table.iloc[test]
    for kind in PERTURBATIONS:
        features = _perturbed_features(frame, kind, config["seed"], spec)
        for name, model in fitted.items():
            scores = model.detector.score(features, frame["seq"].to_numpy())
            counts = score_windows(frame, scores, model.threshold, rule_for())
            robustness.setdefault(name, {})[kind] = report_counts(counts, config)["summary"]

    normal = np.flatnonzero((split == "train") & (table["y"].to_numpy() == 0))
    means = track.features[normal][:, columns_of(track.names, "mean")].astype(float)
    low, median, high = np.nanquantile(means, [0.005, 0.5, 0.995], axis=0)
    definitions = {s.tag: s.measurement_definition_id for s in default_setup()[4]}
    artifacts = {}
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, model in fitted.items():
        path = MODELS / f"aether_{name}.joblib"
        bundle = ModelBundle(
            f"aether_{name}", "1", InputDomain.AETHER_SYNTHETIC, model.detector, spec, model.threshold, rule_for(), CLASS_NAMES,
            definitions, median, np.where(high > low, (high - low) / 2.0, np.nan),
        )  # fmt: skip
        checksum = save_bundle(bundle, path)
        artifacts[name] = {"path": path.name, "sha256": checksum, "bytes": path.stat().st_size}
        tracking.log_run(
            experiment="gate5-aether-synthetic",
            run_name=f"in-regime-{name}",
            params={"method": name, "method_parameters": PARAMETERS[name], "seed": config["seed"], "threshold": model.threshold, "stage": "held_out"},
            metrics=pooled[name]["summary"],
            documents={
                "design.json": load_design(), "evaluation_config.json": config, "features.json": track.names,
                "dataset.json": read_result("aether_dataset"), "hardware.json": hardware(),
            },
            artifact=path,
            artifact_sha256=checksum,
        )  # fmt: skip
    write_result(
        "aether_held_out",
        {
            "track": "SYNTHETIC experiment: uncalibrated fictional AETHER model",
            "git_sha": git_sha(),
            "preferred_from_in_regime": read_result("aether_in_regime")["selection"],
            "regimes": regimes,
            "pooled": pooled,
            "robustness": robustness,
            "gate4_anchors": _gate4_anchors(config, fitted, spec),
            "artifacts": artifacts,
            "hardware": hardware(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["in_regime", "held_out"], required=True)
    if parser.parse_args().stage == "in_regime":
        in_regime()
    else:
        held_out()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
