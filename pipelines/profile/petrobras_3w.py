"""Profile the 3W batch by reading every selected instance from raw."""

from __future__ import annotations

import configparser
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from pipelines.acquire.petrobras_3w.adapter import SOURCE

from .common import FAIL, PASS, WARN, Check, latest_complete, write_report, zero_expected

TRANSIENT_OFFSET = 100


def allowed_labels(directory_label: int) -> set[int]:
    """A file's `class` column may hold normal, its own event, or that event's transient."""
    if directory_label == 0:
        return {0}
    return {0, directory_label, directory_label + TRANSIENT_OFFSET}


def profile_instance(path: Path, directory_label: int) -> dict[str, Any]:
    frame = pq.read_table(path).to_pandas(ignore_metadata=True)
    times = pd.to_datetime(frame["timestamp"])
    steps = times.diff().dropna().dt.total_seconds()
    labels = frame["class"].dropna().astype(int)
    sensors = [c for c in frame.columns if c not in ("timestamp", "class", "state")]
    return {
        "columns": list(frame.columns),
        "rows": len(frame),
        "start": times.min(),
        "end": times.max(),
        "non_increasing_steps": int((steps <= 0).sum()),
        "median_step_s": float(steps.median()) if len(steps) else None,
        "gap_over_60s": int((steps > 60).sum()),
        "unexpected_labels": sorted(
            set(labels.unique().tolist()) - allowed_labels(directory_label)
        ),
        "label_null_rows": int(frame["class"].isna().sum()),
        "state_null_rows": int(frame["state"].isna().sum()),
        "empty_sensors": [c for c in sensors if frame[c].isna().all()],
        "sensor_null_cells": int(frame[sensors].isna().sum().sum()),
        "sensor_cells": int(frame[sensors].size),
    }


def profile(root: Path) -> Path:
    manifest = latest_complete(root, SOURCE)
    batch_id = manifest["batch_id"]
    raw = root / "data" / "raw" / SOURCE / manifest["source_version"] / batch_id
    index = pd.read_parquet(root / "data" / "bronze" / SOURCE / batch_id / "instances.parquet")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(raw / "dataset" / "dataset.ini")
    contract = {k.strip() for k in parser["PARQUET_FILE_PROPERTIES"]}
    units = dict(parser["PARQUET_FILE_PROPERTIES"])

    results = []
    empty_by_origin: dict[str, Counter] = defaultdict(Counter)
    steps: dict[str, Counter] = defaultdict(Counter)
    for row in index.itertuples():
        result = profile_instance(raw / row.source_path, int(row.source_event_label))
        results.append(
            {**result, "instance": row.source_instance_id, "origin": row.real_or_simulated_source}
        )
        empty_by_origin[row.real_or_simulated_source].update(result["empty_sensors"])
        steps[row.real_or_simulated_source][str(result["median_step_s"])] += 1

    frame = pd.DataFrame(results)
    schema_diffs = [r["instance"] for r in results if {c.strip() for c in r["columns"]} != contract]
    bad_labels = [r["instance"] for r in results if r["unexpected_labels"]]

    # Name-derived origin must agree with the bronze label, and only named wells may carry an ID.
    real = index[index["real_or_simulated_source"] == "REAL"]
    generated = index[index["real_or_simulated_source"] != "REAL"]
    origin_errors = (
        int((~real["source_instance_id"].str.startswith("WELL-")).sum())
        + int(generated["source_well_id"].notna().sum())
        + int((real["provenance_class"] != "OBSERVED").sum())
        + int((generated["provenance_class"] != "SYNTHETIC").sum())
    )

    wells_by_class = real.groupby("source_event_label")["source_well_id"].nunique().to_dict()
    too_few_wells = sorted(k for k, v in wells_by_class.items() if v < 2)
    checks = [
        zero_expected(
            "schema_differs_from_dataset_ini", len(schema_diffs), "Columns match the .ini"
        ),
        zero_expected(
            "class_values_outside_directory_label",
            len(bad_labels),
            "`class` holds only 0, the directory label, or label + 100",
        ),
        zero_expected(
            "non_increasing_timestamps",
            frame["non_increasing_steps"].sum(),
            "Timestamps strictly increase within an instance",
        ),
        zero_expected("origin_label_errors", origin_errors, "Origin never relabeled"),
        Check(
            "all_classes_have_real_instances",
            PASS if real["source_event_label"].nunique() == 10 else FAIL,
            int(real["source_event_label"].nunique()),
            "Classes 0-9 each have a real instance",
        ),
        Check(
            "event_classes_with_fewer_than_two_real_wells",
            PASS if not too_few_wells else WARN,
            too_few_wells,
            "Well-grouped evaluation needs 2+ real wells per class",
        ),
        zero_expected(
            "instances_with_time_gaps_over_60s",
            int((frame["gap_over_60s"] > 0).sum()),
            "No gap above 60 s",
            severity=WARN,
        ),
    ]

    report: dict[str, Any] = {
        "batch_id": batch_id,
        "dataset_version": manifest["source_version"],
        "commit": manifest["datasets"]["commit"],
        "record_counts": {
            "instances": len(frame),
            "observations": int(frame["rows"].sum()),
            "real_wells": int(real["source_well_id"].nunique()),
        },
        "instances_by_class_and_origin": manifest["datasets"]["instances_selected"],
        "real_wells_by_class": {str(k): int(v) for k, v in wells_by_class.items()},
        "observations_by_origin": frame.groupby("origin")["rows"].sum().astype(int).to_dict(),
        "median_sampling_step_s_by_origin": {k: dict(v) for k, v in steps.items()},
        "period_real": {
            "first": str(frame[frame.origin == "REAL"]["start"].min()),
            "last": str(frame[frame.origin == "REAL"]["end"].max()),
        },
        "sensor_null_rate_by_origin": {
            origin: round(group["sensor_null_cells"].sum() / group["sensor_cells"].sum(), 4)
            for origin, group in frame.groupby("origin")
        },
        "instances_where_sensor_is_entirely_empty": {
            k: dict(v) for k, v in empty_by_origin.items()
        },
        "label_null_rows": int(frame["label_null_rows"].sum()),
        "state_null_rows": int(frame["state_null_rows"].sum()),
        "documented_units": units,
        "semantic_findings": [
            "dataset.ini gives units but not the pressure reference type, so absolute, gauge, and "
            "differential cannot be distinguished. Treat the reference type as UNKNOWN.",
            "The source describes offshore wells with subsea trees, gas lift, and a DHSV. Physical "
            "compatibility with an onshore gas well must be assessed before any scenario mapping.",
            "`class` is per observation. Transient periods use label + 100 and rows can be null.",
        ],
        "details_of_failing_instances": {"schema": schema_diffs[:20], "labels": bad_labels[:20]},
    }
    return write_report(root, SOURCE, report, checks)
