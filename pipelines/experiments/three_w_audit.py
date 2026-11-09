"""Run the 3W label audit over every acquired instance. Writes the table the benchmark depends on."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import yaml

from packages.anomaly_detection.labels import audit_labels
from packages.anomaly_detection.splits import build_well_folds, class_coverage, credible_classes
from packages.repositories.database import REPO_ROOT

CONFIG = REPO_ROOT / "config" / "experiments" / "gate5_evaluation.yaml"
EXPERIMENTS = REPO_ROOT / "data" / "gold" / "experiments"
ORIGINS = {"REAL": "REAL", "SIMULATED": "SIMULATED", "HAND_DRAWN": "HAND_DRAWN"}


def evaluation_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def batch_root() -> Path:
    found = sorted(glob.glob(str(REPO_ROOT / "data/raw/petrobras_3w/2.0.0/*/dataset")))
    if not found:
        raise FileNotFoundError("3W data is missing. Run `make acquire`.")
    return Path(found[-1]).parent


def instance_table() -> pd.DataFrame:
    found = sorted(glob.glob(str(REPO_ROOT / "data/bronze/petrobras_3w/*/instances.parquet")))
    if not found:
        raise FileNotFoundError("3W instances are missing. Run `make acquire`.")
    table = pd.read_parquet(found[-1])
    table["filed_class"] = table["source_event_label"].astype(int)
    return table


def run_audit() -> pd.DataFrame:
    root = batch_root()
    rows = []
    for item in instance_table().itertuples():
        labels = pq.read_table(root / item.source_path, columns=["class"]).to_pandas(
            ignore_metadata=True
        )["class"]
        rows.append(
            audit_labels(
                pd.to_numeric(labels, errors="coerce").to_numpy(dtype=float),
                instance_id=item.source_instance_id,
                well_id=item.source_well_id,
                origin=ORIGINS[item.real_or_simulated_source],
                filed_class=item.filed_class,
                class_name=item.source_event_class,
            ).to_dict()
        )
    return pd.DataFrame(rows)


def overlap_summary(real: pd.DataFrame) -> dict:
    """Instances on one well that share timestamps, and whether their rows and labels agree."""
    root = batch_root()
    table = instance_table().set_index("source_instance_id")

    def load(instance: str) -> pd.DataFrame:
        frame = pq.read_table(root / table.loc[instance, "source_path"]).to_pandas(
            ignore_metadata=True
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        return frame.set_index("timestamp")

    spans = []
    for instance in real["source_instance_id"]:
        times = pq.read_table(
            root / table.loc[instance, "source_path"], columns=["timestamp"]
        ).to_pandas(ignore_metadata=True)["timestamp"]
        times = pd.to_datetime(times)
        spans.append((table.loc[instance, "source_well_id"], times.min(), times.max(), instance))
    spans.sort()
    pairs = identical = conflicts = shared_seconds = cross_class = 0
    for i, (well, _start, end, instance) in enumerate(spans):
        for other_well, other_start, _, other in spans[i + 1 :]:
            if other_well != well or other_start > end:
                if other_well != well:
                    break
                continue
            a, b = load(instance), load(other)
            shared = a.index.intersection(b.index)
            if shared.empty:
                continue
            sensors = [c for c in a.columns if c not in ("class", "state")]
            same = a.loc[shared, sensors].equals(b.loc[shared, sensors])
            labels_a = pd.to_numeric(a.loc[shared, "class"], errors="coerce")
            labels_b = pd.to_numeric(b.loc[shared, "class"], errors="coerce")
            both = labels_a.notna() & labels_b.notna()
            pairs += 1
            identical += int(same)
            conflicts += int((labels_a[both] != labels_b[both]).any())
            shared_seconds += len(shared)
            cross_class += int(
                table.loc[instance, "source_event_label"] != table.loc[other, "source_event_label"]
            )
    return {
        "pairs": pairs,
        "identical_sensor_rows": identical,
        "label_conflicts": conflicts,
        "shared_hours": round(shared_seconds / 3600, 1),
        "cross_class_pairs": cross_class,
    }


def plausibility_counts() -> dict:
    """Readings per sensor outside the declared limits, by origin. Nothing is written to raw files."""
    from pipelines.experiments.three_w_data import apply_plausibility, sensors_of

    root = batch_root()
    totals: dict[str, dict[str, int]] = {}
    affected: dict[str, set[str]] = {}
    for item in instance_table().itertuples():
        path = root / item.source_path
        sensors = sensors_of(path)
        frame = pq.read_table(path, columns=list(sensors)).to_pandas(ignore_metadata=True)
        _, removed = apply_plausibility(
            frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float), sensors
        )
        for sensor, count in removed.items():
            bucket = totals.setdefault(sensor, {})
            bucket[item.real_or_simulated_source] = (
                bucket.get(item.real_or_simulated_source, 0) + count
            )
            affected.setdefault(sensor, set()).add(item.source_instance_id)
    return {s: {"readings": totals[s], "instances": len(affected[s])} for s in sorted(totals)}


def main() -> int:
    audits = run_audit()
    (EXPERIMENTS / "3w_plausibility.json").parent.mkdir(parents=True, exist_ok=True)
    (EXPERIMENTS / "3w_plausibility.json").write_text(json.dumps(plausibility_counts(), indent=1))
    EXPERIMENTS.mkdir(parents=True, exist_ok=True)
    audits.to_parquet(EXPERIMENTS / "3w_label_audit.parquet", index=False)
    config = evaluation_config()
    real = audits[audits["origin"] == "REAL"]
    split = config["three_w"]["splits"]
    holdout, folds = build_well_folds(
        real,
        holdout_folds=split["holdout_folds"],
        development_folds=split["development_folds"],
        validation_folds=split["validation_folds"],
        seed=config["seed"],
    )
    print(audits.groupby(["origin", "evaluability"]).size().to_string())
    for fold in (holdout, *folds):
        print(fold.name, len(fold.train_wells), len(fold.validation_wells), fold.test_wells)
    coverage = pd.concat([class_coverage(real, f) for f in (holdout, *folds)])
    print(
        coverage.pivot_table(
            index="filed_class", columns=["fold", "side"], values="instances", fill_value=0
        )
        .astype(int)
        .to_string()
    )
    print(
        credible_classes(
            real,
            min_events=config["support"]["min_events"],
            min_clusters=config["support"]["min_clusters"],
        ).to_string()
    )
    from pipelines.experiments.common import write_result

    grades = (
        audits.groupby(["origin", "filed_class", "event_class_name", "evaluability"])
        .agg(
            instances=("source_instance_id", "size"),
            wells=("source_well_id", "nunique"),
            rows=("rows", "sum"),
            null_rows=("null_rows", "sum"),
            event_eligible=("eligible_event_positive", "sum"),
            normal_exposure_eligible=("eligible_normal_exposure", "sum"),
            with_pre_event_normal=("has_pre_event_normal", "sum"),
        )
        .reset_index()
    )
    ambiguous = audits[audits["evaluability"] == "AMBIGUOUS_OR_INCONSISTENT"]
    write_result(
        "3w_label_audit",
        {
            "instances": len(audits),
            "by_grade": grades.to_dict("records"),
            "null_rows_leading_only": bool(audits["null_is_leading_only"].all()),
            "ambiguous": {
                "count": len(ambiguous),
                "wells": ambiguous["source_well_id"].value_counts().to_dict(),
                "rows": int(ambiguous["rows"].sum()),
                "normal_rows": int(ambiguous["normal_rows"].sum()),
                "null_rows": int(ambiguous["null_rows"].sum()),
                "instances": sorted(ambiguous["source_instance_id"]),
            },
            "overlap": overlap_summary(real),
            "plausibility": json.loads((EXPERIMENTS / "3w_plausibility.json").read_text()),
            "coverage": coverage.to_dict("records"),
            "credible_classes": credible_classes(
                real,
                min_events=config["support"]["min_events"],
                min_clusters=config["support"]["min_clusters"],
            ).to_dict("records"),
            "folds": {
                f.name: {
                    "train": f.train_wells,
                    "validation": f.validation_wells,
                    "test": f.test_wells,
                }
                for f in (holdout, *folds)
            },
        },
    )
    (EXPERIMENTS / "3w_splits.json").write_text(
        json.dumps(
            {
                f.name: {
                    "train": f.train_wells,
                    "validation": f.validation_wells,
                    "test": f.test_wells,
                }
                for f in (holdout, *folds)
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
