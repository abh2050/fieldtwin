"""Normalize 3W instances. Sensor values stay in Parquet, and metadata goes to the database."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from packages.domain.models import (
    DataQualityException,
    InstanceOrigin,
    Observation,
    ProvenanceClass,
    SourceAsset,
    SpatialStatus,
    TelemetryEvent,
)

SOURCE = "petrobras_3w"
WELL_CLASS = "OFFSHORE_SUBSEA_WELL"
NON_SENSOR = {"timestamp", "class", "state"}


@dataclass
class W3Canonical:
    wells: list[SourceAsset] = field(default_factory=list)
    events: list[TelemetryEvent] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    exceptions: list[DataQualityException] = field(default_factory=list)


def tag_id(native: str) -> str:
    return f"{SOURCE}:{native}"


def well_asset_id(source_well: str) -> str:
    return f"{SOURCE}:well:{source_well}"


def event_id(label: int, instance: str) -> str:
    # 3W reuses names such as SIMULATED_00001 across classes, so the label is part of the identity.
    return f"{SOURCE}:{label}:{instance}"


def quality_flag(value_count: int, null_count: int) -> str:
    if value_count == 0:
        return "EMPTY"
    return "PARTIAL" if null_count else "COMPLETE"


def normalize_instance(
    row: Any,
    raw_path: Path,
    parquet_uri: str,
    dataset_version: str,
    upstream: str,
    units: dict[str, str],
    batch_id: str,
) -> tuple[TelemetryEvent, list[Observation]]:
    frame = pq.read_table(raw_path).to_pandas(ignore_metadata=True)
    label = int(row.source_event_label)
    origin = InstanceOrigin(row.real_or_simulated_source)
    real = origin is InstanceOrigin.REAL
    provenance = ProvenanceClass.OBSERVED if real else ProvenanceClass.SYNTHETIC
    identifier = event_id(label, row.source_instance_id)
    times = pd.to_datetime(frame["timestamp"])
    event = TelemetryEvent(
        event_id=identifier,
        source_system_id=SOURCE,
        source_instance_id=row.source_instance_id,
        source_asset_id=well_asset_id(row.source_well_id) if real else None,
        source_event_label=label,
        source_event_class=row.source_event_class,
        start_timestamp=times.min().to_pydatetime(),
        end_timestamp=times.max().to_pydatetime(),
        real_or_simulated_source=origin,
        observation_count=len(frame),
        parquet_uri=parquet_uri,
        dataset_version=dataset_version,
        upstream_checksum=upstream,
        provenance_class=provenance,
        batch_id=batch_id,
        transformation_id="3w.real_instance.to_event@1"
        if real
        else "3w.generated_instance.to_event@1",
    )
    series_transformation = (
        "3w.real_series.to_observation@1" if real else "3w.generated_series.to_observation@1"
    )
    observations = []
    for column in frame.columns:
        if column in NON_SENSOR:
            continue
        nulls = int(frame[column].isna().sum())
        values = len(frame) - nulls
        observations.append(
            Observation(
                source_system_id=SOURCE,
                source_record_id=f"{identifier}#{column}",
                observation_type="TELEMETRY_SERIES",
                metric_name=column,
                unit_id=units[column],
                quality_flag=quality_flag(values, nulls),
                provenance_class=provenance,
                original_record_uri=f"{parquet_uri}#column={column}",
                sensor_tag_id=tag_id(column),
                telemetry_event_id=identifier,
                value_count=values,
                null_count=nulls,
                batch_id=batch_id,
                transformation_id=series_transformation,
            )
        )
    return event, observations


def normalize_batch(
    index: pd.DataFrame,
    root: Path,
    manifest: dict[str, Any],
    variables: list[dict[str, Any]],
) -> W3Canonical:
    batch_id = manifest["batch_id"]
    version = manifest["source_version"]
    prefix = f"data/raw/{SOURCE}/{version}/{batch_id}/"
    upstream = {f["path"]: f.get("upstream_checksum") for f in manifest["files"]}
    units = {v["tag"]: v["unit"] for v in variables if "unit" in v}
    result = W3Canonical()

    real_wells = sorted(
        index.loc[index["real_or_simulated_source"] == "REAL", "source_well_id"].unique()
    )
    result.wells = [
        SourceAsset(
            source_asset_id=well_asset_id(well),
            source_system_id=SOURCE,
            asset_type="WELL",
            external_identifier=well,
            equipment_class_id=WELL_CLASS,
            spatial_status=SpatialStatus.NO_LOCATION,
            batch_id=batch_id,
            transformation_id="3w.well.to_source_asset@1",
            source_record_key=well,
        )
        for well in real_wells
    ]
    for row in index.itertuples():
        uri = prefix + row.source_path
        event, observations = normalize_instance(
            row, root / uri, uri, version, upstream[uri], units, batch_id
        )
        result.events.append(event)
        result.observations.extend(observations)

    for variable in variables:
        if variable.get("quantity") == "pressure":
            result.exceptions.append(
                DataQualityException(
                    exception_type="PRESSURE_REFERENCE_UNKNOWN",
                    severity="WARNING",
                    source_system_id=SOURCE,
                    batch_id=batch_id,
                    dataset="sensor_tags",
                    source_record_key=variable["tag"],
                    field_name="pressure_reference_type",
                    original_values={"tag": variable["tag"], "unit": variable["unit"]},
                    evidence={"source": "dataset.ini gives Pa with no reference type"},
                    rule_id="PRESSURE-REFERENCE-KNOWN-1",
                    disposition="FLAGGED_UNRESOLVED",
                    status="OPEN",
                    decision_rationale="The source does not state absolute, gauge, or differential, so the type stays UNKNOWN.",
                )
            )
    return result
