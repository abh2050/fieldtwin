"""3W windows from the acquired files. Raw files are only read, and source labels only copied."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from joblib import Parallel, delayed

from packages.anomaly_detection.evaluation import UNSCORED
from packages.anomaly_detection.features import FeatureSpec, build_features
from packages.anomaly_detection.labels import TRANSIENT_OFFSET
from pipelines.experiments.common import EXPERIMENTS, Track
from pipelines.experiments.three_w_audit import batch_root, evaluation_config

EXCLUDED = {"timestamp", "class", "state"}
WINDOWS = EXPERIMENTS / "3w_windows.parquet"


def sensors_of(path: Path) -> tuple[str, ...]:
    names = pq.read_schema(path).names
    return tuple(n for n in names if n not in EXCLUDED and not n.startswith("__"))


def spec_for(sensors: tuple[str, ...]) -> FeatureSpec:
    config = evaluation_config()["three_w"]
    return FeatureSpec(sensors, config["window_s"], config["stride_s"], 1)


def plausible_limits(sensor: str) -> tuple[float, float] | None:
    limits = evaluation_config()["three_w"]["plausibility"]
    if sensor.startswith(("P-", "PT-")):
        return tuple(limits["pressure_pa"])
    if sensor.startswith("T-"):
        return tuple(limits["temperature_c"])
    if sensor.startswith("ABER-"):
        return tuple(limits["opening_percent"])
    return None


def apply_plausibility(
    values: np.ndarray, sensors: tuple[str, ...]
) -> tuple[np.ndarray, dict[str, int]]:
    """Set impossible readings to missing, using no label. Returns the count removed per sensor."""
    output = values.copy()
    removed = {}
    with np.errstate(invalid="ignore"):
        for i, sensor in enumerate(sensors):
            limits = plausible_limits(sensor)
            if limits is None:
                continue
            outside = (output[:, i] < limits[0]) | (output[:, i] > limits[1])
            if outside.any():
                removed[sensor] = int(outside.sum())
                output[outside, i] = np.nan
    return output, removed


def read_instance(
    path: Path, sensors: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame = pq.read_table(path).to_pandas(ignore_metadata=True)
    times = (
        (pd.to_datetime(frame["timestamp"]) - pd.Timestamp(0))
        .dt.total_seconds()
        .to_numpy()
        .astype(np.int64)
    )
    values = frame[list(sensors)].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    values, _ = apply_plausibility(values, sensors)
    labels = pd.to_numeric(frame["class"], errors="coerce").to_numpy(dtype=float)
    return values, times, labels


def to_class(raw: np.ndarray) -> np.ndarray:
    """Map a source label to a class for scoring. Transient k+100 becomes k, and null is unscored."""
    output = np.full(raw.shape, UNSCORED, dtype=np.int16)
    known = ~np.isnan(raw)
    output[known] = raw[known].astype(np.int16) % TRANSIENT_OFFSET
    return output


def _one(row: dict, path: Path, spec: FeatureSpec) -> pd.DataFrame:
    values, times, labels = read_instance(path, spec.sensors)
    features, ends = build_features(values, times, spec)
    frame = pd.DataFrame(features, columns=spec.names)
    frame.insert(0, "t", times[ends])
    frame.insert(1, "raw_label", np.nan_to_num(labels[ends], nan=-1).astype(np.int16))
    frame.insert(2, "source_y", to_class(labels[ends]))
    frame.insert(0, "seq", row["source_instance_id"])
    frame.insert(1, "well", row["source_well_id"] or row["source_instance_id"])
    frame.insert(2, "origin", row["origin"])
    frame.insert(3, "filed_class", row["filed_class"])
    frame.insert(4, "evaluability", row["evaluability"])
    return frame


def build_windows() -> None:
    audits = pd.read_parquet(EXPERIMENTS / "3w_label_audit.parquet")
    root = batch_root()
    paths = {f.stem: f for f in root.glob("dataset/*/*.parquet")}
    first = paths[audits["source_instance_id"].iloc[0]]
    spec = spec_for(sensors_of(first))
    parts = Parallel(n_jobs=8)(
        delayed(_one)(row, paths[row["source_instance_id"]], spec)
        for row in audits.to_dict("records")
    )
    pd.concat(parts, ignore_index=True).to_parquet(WINDOWS, index=False)


def load_track() -> tuple[Track, pd.DataFrame, FeatureSpec]:
    if not WINDOWS.exists():
        build_windows()
    frame = pd.read_parquet(WINDOWS)
    meta_columns = [
        "seq",
        "well",
        "origin",
        "filed_class",
        "evaluability",
        "t",
        "raw_label",
        "source_y",
    ]
    names = [c for c in frame.columns if c not in meta_columns]
    table = frame[meta_columns].copy()
    table["cluster"] = table["well"]
    # The primary rule: ambiguous instances are on neither side of any metric.
    table["y"] = np.where(
        table["evaluability"] == "AMBIGUOUS_OR_INCONSISTENT", UNSCORED, table["source_y"]
    ).astype(np.int16)
    sensors = tuple(n.split("__")[0] for n in names[0::4])
    return (
        Track(frame[names].to_numpy(dtype=np.float32), names, table),
        frame[meta_columns],
        spec_for(sensors),
    )


def dataset_sha256() -> str:
    digest = hashlib.sha256()
    for path in sorted(batch_root().glob("dataset/*/*.parquet")):
        digest.update(path.name.encode())
        digest.update(str(path.stat().st_size).encode())
    return digest.hexdigest()


def with_policy(table: pd.DataFrame, policy: str) -> pd.DataFrame:
    """Scoring variants for ambiguous instances, used only in sensitivity analysis. Nothing is relabeled."""
    output = table.copy()
    ambiguous = (output["evaluability"] == "AMBIGUOUS_OR_INCONSISTENT").to_numpy()
    known = (output["source_y"] != UNSCORED).to_numpy()
    y = output["y"].to_numpy(dtype=np.int16, copy=True)
    if policy == "count_as_positive":
        y[ambiguous & known] = output["filed_class"].to_numpy(dtype=np.int16)[ambiguous & known]
    elif policy == "count_as_normal":
        y[ambiguous & known] = 0
    elif policy != "excluded":
        raise ValueError(policy)
    output["y"] = y
    return output
