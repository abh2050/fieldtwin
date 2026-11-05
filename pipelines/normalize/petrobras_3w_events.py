"""Benchmark event adapter: 3W instances in the shared event contract, with no AETHER link.

The onset is the first observation carrying a non-normal source label. Labels are not changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import psycopg
import pyarrow.parquet as pq

from packages.domain.events import EventDomain, EventKind, SharedEvent
from packages.domain.models import ProvenanceClass
from packages.repositories.database import REPO_ROOT, connect

REAL_TRANSFORMATION = "3w.benchmark_event_adapter.real@1"
GENERATED_TRANSFORMATION = "3w.benchmark_event_adapter.generated@1"


def label_onset_offset_s(path: Path) -> int | None:
    """Seconds from the instance start to the first non-normal label, or None if there isn't one."""
    table = pq.read_table(path, columns=["timestamp", "class"]).to_pandas(ignore_metadata=True)
    times = pd.to_datetime(table["timestamp"])
    labelled = table["class"].notna() & (table["class"] != 0)
    if not labelled.any():
        return None
    first = times[labelled].min()
    return int((first - times.min()).total_seconds())


def to_shared_event(
    event_id: str,
    instance: str,
    label: int,
    event_class: str,
    origin: str,
    source_asset: str | None,
    uri: str,
    onset: int | None,
) -> SharedEvent:
    real = origin == "REAL"
    return SharedEvent(
        event_id=f"benchmark:{event_id}",
        domain=EventDomain.OFFSHORE_BENCHMARK,
        event_kind=EventKind.SOURCE_LABEL,
        event_class=event_class,
        source_system_id="petrobras_3w",
        telemetry_event_id=event_id,
        onset_offset_s=onset,
        evidence={
            "source_instance_id": instance,
            "source_event_label": label,
            "real_or_simulated_source": origin,
            "source_well": source_asset,
            "parquet_uri": uri,
            "onset_basis": "first observation with a non-normal class label"
            if onset is not None
            else "none",
        },
        provenance_class=ProvenanceClass.DERIVED if real else ProvenanceClass.SYNTHETIC,
        transformation_id=REAL_TRANSFORMATION if real else GENERATED_TRANSFORMATION,
    )


def adapt_events(conn: psycopg.Connection, root: Path) -> list[SharedEvent]:
    events = []
    for event_id, instance, label, event_class, origin, asset, uri in conn.execute(
        """SELECT event_id, source_instance_id, source_event_label, source_event_class,
                  real_or_simulated_source, source_asset_id, parquet_uri
           FROM telemetry_events ORDER BY event_id"""
    ):
        onset = label_onset_offset_s(root / uri)
        events.append(
            to_shared_event(event_id, instance, label, event_class, origin, asset, uri, onset)
        )
    return events


def insert_events(conn: psycopg.Connection, events: list[SharedEvent]) -> int:
    if not events:
        return 0
    rows = []
    for event in events:
        row = event.model_dump(mode="json")
        row["evidence"] = json.dumps(row["evidence"])
        rows.append(row)
    columns = list(rows[0])
    marks = ", ".join(f"%({c})s" for c in columns)
    sql = f"INSERT INTO shared_events ({', '.join(columns)}) VALUES ({marks}) ON CONFLICT (event_id) DO NOTHING"
    with conn.cursor() as cursor:
        cursor.executemany(sql, rows)
    return len(rows)


def flag_unlabelled_instances(conn: psycopg.Connection, events: list[SharedEvent]) -> int:
    """A non-normal class directory with no non-normal labels must not pass as a labeled event."""
    flagged = [e for e in events if e.onset_offset_s is None and e.event_class != "NORMAL"]
    batches: dict[str, str] = dict(
        conn.execute("SELECT event_id, batch_id FROM telemetry_events").fetchall()
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO data_quality_exceptions (exception_type, severity, source_system_id, batch_id, dataset,
                 source_record_key, field_name, original_values, evidence, rule_id, disposition, status, decision_rationale)
               VALUES ('BENCHMARK_INSTANCE_WITHOUT_EVENT_LABEL', 'WARNING', 'petrobras_3w', %s, 'telemetry_events', %s,
                 'class', %s, %s, '3W-EVENT-LABEL-PRESENT-1', 'FLAGGED_UNRESOLVED', 'OPEN', %s)
               ON CONFLICT (batch_id, rule_id, source_record_key) DO NOTHING""",
            [
                (
                    batches[str(e.telemetry_event_id)],
                    e.telemetry_event_id,
                    json.dumps({"event_class": e.event_class}),
                    json.dumps({"finding": "The class column holds only normal or null labels."}),
                    "Filed under an event class but carries no event label. Labels are kept as published, "
                    "and Gate 5 must decide how to evaluate these instances.",
                )
                for e in flagged
            ],
        )
    return len(flagged)


def load_benchmark_events(conn: psycopg.Connection, root: Path = REPO_ROOT) -> int:
    with conn.transaction():
        events = adapt_events(conn, root)
        flag_unlabelled_instances(conn, events)
        return insert_events(conn, events)


def main() -> int:
    with connect() as conn:
        print(f"benchmark_events={load_benchmark_events(conn)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
