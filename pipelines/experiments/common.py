"""Shared experiment steps, so both tracks follow the same rules. Their results are never pooled."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from packages.anomaly_detection.detectors import PARAMETERS, Detector, make_detector, training_rows
from packages.anomaly_detection.evaluation import (
    UNSCORED,
    AlarmRule,
    ClusterCounts,
    average_precision,
    bootstrap_intervals,
    by_class,
    calibrate_threshold,
    score_windows,
    summarize,
)
from packages.repositories.database import REPO_ROOT

EXPERIMENTS = REPO_ROOT / "data" / "gold" / "experiments"
RESULTS = REPO_ROOT / "reports" / "experiments" / "results"
MODELS = EXPERIMENTS / "models"


@dataclass
class Track:
    """Windows for one track. `table` has seq, cluster, t, y, and row order is time order in a seq."""

    features: np.ndarray
    names: list[str]
    table: pd.DataFrame


@dataclass
class Fitted:
    method: str
    detector: Detector
    threshold: float
    columns: np.ndarray
    names: list[str]
    calibration: dict
    fit_seconds: float
    training_rows: int


def rule_from(track_config: dict) -> AlarmRule:
    stride = track_config.get("stride_s", 300)
    return AlarmRule(track_config["persistence_windows"], track_config["suppression_s"], stride)


def fit_and_calibrate(
    method: str,
    track: Track,
    train: np.ndarray,
    validation: np.ndarray,
    config: dict,
    track_config: dict,
    *,
    columns: np.ndarray | None = None,
) -> Fitted:
    """Fit on training rows only, then set the threshold on validation rows only."""
    columns = np.arange(len(track.names)) if columns is None else columns
    names = [track.names[i] for i in columns]
    y = track.table["y"].to_numpy()
    seq = track.table["seq"].to_numpy()
    started = time.perf_counter()
    detector = make_detector(
        method,
        names,
        seed=config["seed"],
        baseline_windows=track_config["rolling_baseline_windows"],
        gap_windows=track_config["rolling_gap_windows"],
    )
    # A rolling baseline reads each series' own past, so it fits its noise floor from labeled rows
    # and needs no sequence structure from training.
    rows = training_rows(
        y[train], cap_per_class=track_config["max_train_windows_per_class"], seed=config["seed"]
    )
    chosen = train[rows]
    detector.fit(track.features[chosen][:, columns], y[chosen], seq[chosen])
    fit_seconds = time.perf_counter() - started
    scores = detector.score(track.features[validation][:, columns], seq[validation])
    calibration = calibrate_threshold(
        track.table.iloc[validation],
        scores,
        rule_from(track_config),
        budget=config["alarm"]["false_alarms_per_hour_budget"],
        grid_points=config["alarm"]["threshold_grid_points"],
        max_time_in_alarm=config["alarm"]["max_fraction_of_normal_time_in_alarm"],
    )
    calibration["fit_report"] = getattr(detector, "fit_report", None)
    return Fitted(
        method,
        detector,
        calibration["threshold"],
        columns,
        names,
        calibration,
        fit_seconds,
        len(chosen),
    )


def score_rows(fitted: Fitted, track: Track, rows: np.ndarray) -> np.ndarray:
    return fitted.detector.score(
        track.features[rows][:, fitted.columns], track.table["seq"].to_numpy()[rows]
    )


def merge_counts(parts: list[ClusterCounts]) -> ClusterCounts:
    """Combine results from folds whose clusters don't overlap."""
    return ClusterCounts(
        pd.concat([p.table for p in parts]), pd.concat([p.events for p in parts], ignore_index=True)
    )


def report_counts(counts: ClusterCounts, config: dict) -> dict:
    uncertainty, support = config["uncertainty"], config["support"]
    summary = summarize(counts)
    interval: dict = {}
    if summary["clusters"] >= support["min_clusters_for_interval"]:
        interval = bootstrap_intervals(
            counts,
            resamples=uncertainty["bootstrap_resamples"],
            confidence=uncertainty["confidence"],
            seed=config["seed"],
        )
    if summary["event_clusters"] < support["min_clusters_for_interval"]:
        interval.pop("event_recall", None)
        interval.pop("event_skill", None)
    classes = by_class(
        counts,
        support,
        resamples=uncertainty["bootstrap_resamples"],
        confidence=uncertainty["confidence"],
        seed=config["seed"],
    )
    if (
        summary["events"] < support["min_events"]
        or summary["event_clusters"] < support["min_clusters"]
    ):
        summary["event_recall"] = None
        summary["event_skill"] = None
        summary["chance_event_recall"] = None
        summary["event_recall_withheld"] = True
    return {"summary": summary, "interval": interval, "by_class": classes}


def evaluate_rows(
    fitted: Fitted,
    track: Track,
    rows: np.ndarray,
    rule: AlarmRule,
    table: pd.DataFrame | None = None,
) -> tuple[ClusterCounts, np.ndarray, float | None]:
    frame = track.table.iloc[rows] if table is None else table.iloc[rows]
    scores = score_rows(fitted, track, rows)
    return (
        score_windows(frame, scores, fitted.threshold, rule),
        scores,
        average_precision(frame, scores),
    )


def scores_sha256(scores: np.ndarray) -> str:
    """Rounded, to compare runs on one machine while ignoring meaningless low-order bits."""
    return hashlib.sha256(
        np.round(np.nan_to_num(scores, nan=-1e30, posinf=1e30), 6).tobytes()
    ).hexdigest()


def confusion(fitted: Fitted, track: Track, rows: np.ndarray, class_ids: list[int]) -> dict | None:
    """Per-class window counts, for methods that predict a class. Each well and time counts once."""
    predicted = fitted.detector.predict_class(track.features[rows][:, fitted.columns])
    if predicted is None:
        return None
    frame = track.table.iloc[rows].reset_index(drop=True)
    keep = (~frame.duplicated(["cluster", "t"])).to_numpy() & (frame["y"].to_numpy() != UNSCORED)
    truth, guess = frame["y"].to_numpy()[keep], np.asarray(predicted)[keep]
    index = {c: i for i, c in enumerate(class_ids)}
    matrix = np.zeros((len(class_ids), len(class_ids)), dtype=int)
    for t, g in zip(truth.tolist(), guess.tolist(), strict=True):
        matrix[index[int(t)], index[int(g)]] += 1
    return {"classes": class_ids, "matrix": matrix.tolist()}


def hardware() -> dict:
    cpu = platform.processor() or platform.machine()
    return {
        "platform": platform.platform(aliased=True, terse=True),
        "machine": platform.machine(),
        "processor": cpu,
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "memory_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1),
    }


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def write_result(name: str, payload: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True, default=_plain) + "\n"
    )


def read_result(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text())


def _plain(value):
    if isinstance(value, np.integer | np.bool_):
        return value.item()
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


__all__ = ["PARAMETERS", "EXPERIMENTS", "MODELS", "RESULTS", "Fitted", "Track"]
