"""The 3W benchmark. `--stage development` chooses a method, and `--stage holdout` opens the holdout."""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from packages.anomaly_detection.contracts import InputDomain
from packages.anomaly_detection.detectors import make_detector, training_rows
from packages.anomaly_detection.evaluation import (
    UNSCORED,
    average_precision,
    score_windows,
    select_preferred,
)
from packages.anomaly_detection.features import FeatureSpec, build_features, columns_of
from packages.anomaly_detection.inference import ModelBundle, save_bundle
from packages.anomaly_detection.splits import build_well_folds, class_coverage, credible_classes
from pipelines.experiments import tracking
from pipelines.experiments.common import (
    EXPERIMENTS,
    MODELS,
    PARAMETERS,
    confusion,
    evaluate_rows,
    fit_and_calibrate,
    git_sha,
    hardware,
    merge_counts,
    read_result,
    report_counts,
    rule_from,
    scores_sha256,
    write_result,
)
from pipelines.experiments.three_w_audit import batch_root, evaluation_config
from pipelines.experiments.three_w_data import (
    dataset_sha256,
    load_track,
    read_instance,
    with_policy,
)

CLASSES = list(range(10))
CLASS_NAMES = {
    0: "NORMAL", 1: "ABRUPT_INCREASE_OF_BSW", 2: "SPURIOUS_CLOSURE_OF_DHSV", 3: "SEVERE_SLUGGING", 4: "FLOW_INSTABILITY",
    5: "RAPID_PRODUCTIVITY_LOSS", 6: "QUICK_RESTRICTION_IN_PCK", 7: "SCALING_IN_PCK", 8: "HYDRATE_IN_PRODUCTION_LINE", 9: "HYDRATE_IN_SERVICE_LINE",
}  # fmt: skip
PERTURBATIONS = ("sensors_25pct_removed", "rows_20pct_missing", "ten_minute_outage_each_hour")


def _folds(config: dict, instances: pd.DataFrame):
    split = config["three_w"]["splits"]
    return build_well_folds(
        instances,
        holdout_folds=split["holdout_folds"],
        development_folds=split["development_folds"],
        validation_folds=split["validation_folds"],
        seed=config["seed"],
    )


def _rows(table: pd.DataFrame, wells, *, real_only: bool = True) -> np.ndarray:
    mask = table["well"].isin(wells).to_numpy()
    if real_only:
        mask = mask & (table["origin"] == "REAL").to_numpy()
    return np.flatnonzero(mask)


def _instances(table: pd.DataFrame) -> pd.DataFrame:
    audits = pd.read_parquet(EXPERIMENTS / "3w_label_audit.parquet")
    return audits[audits["origin"] == "REAL"]


def development() -> None:
    config = evaluation_config()
    settings = config["three_w"]
    track, _, _ = load_track()
    instances = _instances(track.table)
    _, folds = _folds(config, instances)
    rule = rule_from(settings)
    table = track.table
    methods = {}
    sensitivity: dict = {}
    for method in config["methods"]:
        parts, ap, thresholds, fit_s, hashes = [], [], {}, 0.0, {}
        policy_parts: dict[str, list] = {
            "count_as_positive": [],
            "count_as_normal": [],
            "leading_unlabeled_as_normal": [],
        }
        for fold in folds:
            train, validation, test = (
                _rows(table, w) for w in (fold.train_wells, fold.validation_wells, fold.test_wells)
            )
            fitted = fit_and_calibrate(method, track, train, validation, config, settings)
            counts, scores, precision = evaluate_rows(fitted, track, test, rule)
            parts.append(counts)
            ap.append(precision)
            thresholds[fold.name] = fitted.calibration
            fit_s += fitted.fit_seconds
            hashes[fold.name] = scores_sha256(scores)
            for policy, bucket in policy_parts.items():
                bucket.append(
                    score_windows(
                        with_policy(table, policy).iloc[test], scores, fitted.threshold, rule
                    )
                )
            print(
                method,
                fold.name,
                "thr",
                round(fitted.threshold, 4),
                "met",
                fitted.calibration["budget_met"],
                flush=True,
            )
        result = report_counts(merge_counts(parts), config)
        result |= {
            "mean_fold_average_precision": float(np.mean([a for a in ap if a is not None])),
            "calibration": thresholds,
            "fit_seconds": fit_s,
            "scores_sha256": hashes,
        }
        methods[method] = result
        sensitivity[method] = {
            p: report_counts(merge_counts(b), config)["summary"] for p, b in policy_parts.items()
        }
        s = result["summary"]
        print(
            method,
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
    rows = [
        {
            "method": m,
            "event_skill": r["summary"]["event_skill"] or 0.0,
            "false_alarms_per_hour": r["summary"]["false_alarms_per_hour"],
            "interval": r["interval"],
        }
        for m, r in methods.items()
    ]
    selection = select_preferred(
        rows, order=config["methods"], budget=config["alarm"]["false_alarms_per_hour_budget"]
    )
    write_result(
        "3w_development",
        {
            "track": "OBSERVED benchmark: Petrobras 3W recorded instances",
            "git_sha": git_sha(),
            "dataset_sha256": dataset_sha256(),
            "folds": [f.__dict__ for f in folds],
            "methods": methods,
            "ambiguous_sensitivity": sensitivity,
            "variants": _variants(config, track, folds, rule),
            "leakage_contrast": _leakage_contrast(config, track, folds),
            "selection": selection,
            "hardware": hardware(),
        },
    )
    print(json.dumps(selection, indent=1))


def _variants(config, track, folds, rule) -> dict:
    """Training changes for the most complex method, measured on development folds."""
    settings = config["three_w"]
    table = track.table
    all_columns = np.arange(len(track.names))
    variants = {
        "no_level_features": np.setdiff1d(all_columns, columns_of(track.names, "mean")),
        "no_missingness_features": np.setdiff1d(all_columns, columns_of(track.names, "missing")),
        "with_generated_training_data": all_columns,
    }
    output = {}
    for name, columns in variants.items():
        parts, ap = [], []
        for fold in folds:
            train = _rows(table, fold.train_wells)
            if name == "with_generated_training_data":
                generated = np.flatnonzero((table["origin"] != "REAL").to_numpy())
                train = np.concatenate([train, generated])
            validation, test = _rows(table, fold.validation_wells), _rows(table, fold.test_wells)
            fitted = fit_and_calibrate(
                "hist_gradient_boosting",
                track,
                train,
                validation,
                config,
                settings,
                columns=columns,
            )
            counts, _, precision = evaluate_rows(fitted, track, test, rule)
            parts.append(counts)
            ap.append(precision)
        output[name] = report_counts(merge_counts(parts), config)["summary"] | {
            "mean_fold_average_precision": float(np.mean([a for a in ap if a is not None]))
        }
        print(
            "variant",
            name,
            output[name]["event_recall"],
            output[name]["false_alarms_per_hour"],
            flush=True,
        )
    return output


def _leakage_contrast(config, track, folds) -> dict:
    """The optimism from splitting badly. These numbers are invalid as estimates, and are shown as a warning."""
    settings = config["three_w"]
    table = track.table
    wells = sorted({w for f in folds for w in f.test_wells})
    rows = _rows(table, wells)
    rows = rows[table["y"].to_numpy()[rows] != UNSCORED]
    rng = np.random.default_rng(config["seed"])
    output = {}
    seqs = table["seq"].to_numpy()[rows]
    unique = np.array(sorted(set(seqs)))
    held_instances = set(rng.choice(unique, len(unique) // 5, replace=False).tolist())
    in_test = np.array([s in held_instances for s in seqs])
    random_row = rng.random(len(rows)) < 0.2
    for name, mask in (("random_rows", random_row), ("random_instances", in_test)):
        train, test = rows[~mask], rows[mask]
        y = table["y"].to_numpy()
        chosen = train[
            training_rows(
                y[train], cap_per_class=settings["max_train_windows_per_class"], seed=config["seed"]
            )
        ]
        model = make_detector(
            "hist_gradient_boosting",
            track.names,
            seed=config["seed"],
            baseline_windows=1,
            gap_windows=1,
        )
        model.fit(track.features[chosen], y[chosen], seqs[:0])
        output[name] = {
            "average_precision": average_precision(
                table.iloc[test], model.score(track.features[test], seqs[:0])
            )
        }
    return output


def _perturb(values: np.ndarray, kind: str, rng: np.random.Generator) -> np.ndarray:
    output = values.copy()
    if kind == "sensors_25pct_removed":
        present = np.flatnonzero((~np.isnan(values)).any(axis=0))
        if present.size:
            output[:, rng.choice(present, max(1, present.size // 4), replace=False)] = np.nan
    elif kind == "rows_20pct_missing":
        output[rng.random(values.shape) < 0.2] = np.nan
    elif kind == "ten_minute_outage_each_hour":
        output[np.arange(len(values)) % 3600 < 600] = np.nan
    else:
        raise ValueError(kind)
    return output


def _perturbed_instance(
    path, seq: str, spec: FeatureSpec, kind: str, seed: int
) -> tuple[str, np.ndarray]:
    values, times, _ = read_instance(path, spec.sensors)
    rng = np.random.default_rng(
        np.random.SeedSequence(
            [seed, int(hashlib.sha256(f"{seq}|{kind}".encode()).hexdigest()[:8], 16)]
        )
    )
    features, _ = build_features(_perturb(values, kind, rng), times, spec)
    return seq, features


def holdout() -> None:
    config = evaluation_config()
    settings = config["three_w"]
    track, _, spec = load_track()
    instances = _instances(track.table)
    fold, _ = _folds(config, instances)
    rule = rule_from(settings)
    table = track.table
    train, validation, test = (
        _rows(table, w) for w in (fold.train_wells, fold.validation_wells, fold.test_wells)
    )
    selection = read_result("3w_development")["selection"]
    # Holdout sequences are real instances, whose names are unique.
    paths = {
        f.stem: f for f in batch_root().glob("dataset/*/*.parquet") if f.stem.startswith("WELL-")
    }
    test_seqs = list(pd.unique(table["seq"].to_numpy()[test]))
    perturbed: dict[str, np.ndarray] = {}
    for kind in PERTURBATIONS:
        pieces = dict(
            Parallel(n_jobs=8)(
                delayed(_perturbed_instance)(paths[s], s, spec, kind, config["seed"])
                for s in test_seqs
            )
        )
        order = table["seq"].to_numpy()[test]
        perturbed[kind] = np.concatenate([pieces[s] for s in pd.unique(order)])
    methods: dict = {}
    robustness: dict = {}
    sensitivity: dict = {}
    artifacts: dict = {}
    MODELS.mkdir(parents=True, exist_ok=True)
    normal = train[table["y"].to_numpy()[train] == 0]
    means = track.features[normal][:, columns_of(track.names, "mean")].astype(float)
    low, median, high = np.nanquantile(means, [0.005, 0.5, 0.995], axis=0)
    for method in config["methods"]:
        fitted = fit_and_calibrate(method, track, train, validation, config, settings)
        counts, scores, precision = evaluate_rows(fitted, track, test, rule)
        methods[method] = report_counts(counts, config) | {
            "average_precision": precision,
            "threshold": fitted.threshold,
            "calibration": fitted.calibration,
            "fit_seconds": fitted.fit_seconds,
            "training_rows": fitted.training_rows,
            "confusion": confusion(fitted, track, test, CLASSES),
            "scores_sha256": scores_sha256(scores),
        }
        sensitivity[method] = {
            p: report_counts(
                score_windows(with_policy(table, p).iloc[test], scores, fitted.threshold, rule),
                config,
            )["summary"]
            for p in ("count_as_positive", "count_as_normal", "leading_unlabeled_as_normal")
        }
        robustness[method] = {}
        seqs = table["seq"].to_numpy()[test]
        for kind, features in perturbed.items():
            altered = fitted.detector.score(features, seqs)
            robustness[method][kind] = report_counts(
                score_windows(table.iloc[test], altered, fitted.threshold, rule), config
            )["summary"]
        path = MODELS / f"3w_{method}.joblib"
        bundle = ModelBundle(
            f"3w_{method}", "1", InputDomain.OFFSHORE_BENCHMARK, fitted.detector, spec, fitted.threshold, rule, CLASS_NAMES,
            {s: f"petrobras_3w.{s}" for s in spec.sensors}, median, np.where(high > low, (high - low) / 2.0, np.nan),
        )  # fmt: skip
        checksum = save_bundle(bundle, path)
        artifacts[method] = {"path": path.name, "sha256": checksum, "bytes": path.stat().st_size}
        tracking.log_run(
            experiment="gate5-3w-observed-benchmark",
            run_name=f"holdout-{method}",
            params={"method": method, "method_parameters": PARAMETERS[method], "seed": config["seed"], "stage": "holdout", "window_s": settings["window_s"], "stride_s": settings["stride_s"], "threshold": fitted.threshold},
            metrics=methods[method]["summary"],
            documents={
                "split.json": fold.__dict__, "evaluation_config.json": config, "features.json": track.names,
                "dataset.json": {"sha256": dataset_sha256(), "source": "petrobras_3w", "provenance": "OBSERVED", "manifest": tracking.source_manifests("petrobras_3w")},
                "hardware.json": hardware(),
            },
            artifact=path,
            artifact_sha256=checksum,
        )  # fmt: skip
        s = methods[method]["summary"]
        print(method, "recall", s["event_recall"], "FA/h", s["false_alarms_per_hour"], flush=True)
    coverage = class_coverage(instances, fold).to_dict("records")
    write_result(
        "3w_holdout",
        {
            "track": "OBSERVED benchmark: Petrobras 3W recorded instances",
            "git_sha": git_sha(),
            "dataset_sha256": dataset_sha256(),
            "preferred_from_development": selection,
            "fold": fold.__dict__,
            "coverage": coverage,
            "credible_classes": credible_classes(
                instances,
                min_events=config["support"]["min_events"],
                min_clusters=config["support"]["min_clusters"],
            ).to_dict("records"),
            "methods": methods,
            "ambiguous_sensitivity": sensitivity,
            "robustness": robustness,
            "artifacts": artifacts,
            "hardware": hardware(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["development", "holdout"], required=True)
    args = parser.parse_args()
    if args.stage == "development":
        development()
    else:
        holdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
