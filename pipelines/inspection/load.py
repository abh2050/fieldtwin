"""Load Gate 6 evidence into the canonical schema: observations, proximity and coverage links,
reviews, and inspection requests. Run after `make db-load` and the inspection stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from packages.inspection.review import ReviewLedger
from packages.repositories.database import REPO_ROOT, connect
from pipelines.normalize.load import _batch_loaded, _insert_batch

from .associate import SILVER
from .wells import latest_batch

GOLD = Path("data") / "gold" / "inspection"
PLUME_TRANSFORM = "carbon_mapper.plume.to_observation@1"
CHIP_TRANSFORM = "naip.chip.to_observation@1"


def _none(value: Any) -> Any:
    return None if value in (None, "", "None", "nan") else value


def _plume_rows(plumes: pd.DataFrame, batch_id: str, raw_root: str) -> list[dict[str, Any]]:
    return [
        {
            "source_record_id": p["plume_id"],
            "observed_at": p["scene_timestamp"].replace("Z", "").replace("T", " "),
            "numeric_value": _none(p["emission_auto"]),
            "quality_flag": _none(p["plume_quality"]) or "AS_PUBLISHED",
            "lon": float(p["longitude"]),
            "lat": float(p["latitude"]),
            "uri": f"{raw_root}/plumes#plume_id={p['plume_id']}",
            "batch_id": batch_id,
        }
        for p in plumes.to_dict("records")
    ]


def load_inspection(conn: psycopg.Connection, root: Path = REPO_ROOT) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    cm = latest_batch(root, "carbon_mapper")
    naip = latest_batch(root, "naip")
    plumes = pd.read_parquet(root / "data/bronze/carbon_mapper" / cm["batch_id"] / "plumes.parquet")
    chips = pd.read_parquet(root / "data/bronze/naip" / naip["batch_id"] / "chips.parquet")
    links = pd.read_parquet(root / SILVER / "proximity_links.parquet")

    with conn.transaction():
        for manifest in (cm, naip):
            if not _batch_loaded(conn, manifest["batch_id"]):
                _insert_batch(conn, manifest)
        raw_cm = f"data/raw/carbon_mapper/{cm['source_version']}/{cm['batch_id']}"
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO observations (source_system_id, source_record_id, observed_at, observation_type,
                     metric_name, numeric_value, unit_id, quality_flag, geometry, provenance_class,
                     original_record_uri, batch_id, transformation_id)
                   VALUES ('carbon_mapper', %(source_record_id)s, %(observed_at)s, 'REMOTE_SENSING',
                     'ch4_plume_emission_rate', %(numeric_value)s, 'kg_per_h', %(quality_flag)s,
                     ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), 'OBSERVED', %(uri)s, %(batch_id)s,
                     'carbon_mapper.plume.to_observation@1')
                   ON CONFLICT (source_system_id, source_record_id) DO NOTHING""",
                _plume_rows(plumes, cm["batch_id"], raw_cm),
            )
            cursor.executemany(
                """INSERT INTO observations (source_system_id, source_record_id, observed_at, observation_type,
                     metric_name, numeric_value, unit_id, quality_flag, geometry, provenance_class,
                     original_record_uri, batch_id, transformation_id)
                   VALUES ('naip', %(chip_id)s, %(acquisition_date)s, 'IMAGE', 'naip_rgbn_image', NULL, NULL,
                     'AS_PUBLISHED', ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326),
                     'OBSERVED', %(path)s, %(batch_id)s, 'naip.chip.to_observation@1')
                   ON CONFLICT (source_system_id, source_record_id) DO NOTHING""",
                [
                    {
                        **c,
                        "west": float(c["west"]),
                        "south": float(c["south"]),
                        "east": float(c["east"]),
                        "north": float(c["north"]),
                        "batch_id": naip["batch_id"],
                    }
                    for c in chips.to_dict("records")
                ],
            )
        ids: dict[str, int] = dict(
            conn.execute(
                "SELECT source_system_id || ':' || source_record_id, observation_id FROM observations "
                "WHERE source_system_id IN ('carbon_mapper', 'naip')"
            ).fetchall()
        )
        known_wells = {
            r[0] for r in conn.execute("SELECT source_asset_id FROM source_assets").fetchall()
        }
        link_rows = []
        for link in links.to_dict("records"):
            if link["source_asset_id"] not in known_wells:
                continue
            link_rows.append(
                {
                    "source_asset_id": link["source_asset_id"],
                    "observation_id": ids[f"carbon_mapper:{link['plume_id']}"],
                    "relationship_type": "EMISSION_NEAR",
                    "evidence_reference": (
                        f"distance_m={link['distance_m']};rank={link['rank']};"
                        f"candidates_within_radius={link['candidates_within_radius']};radius_m={link['radius_m']}"
                    ),
                    "method_version": link["method_version"],
                    "provenance_class": "DERIVED",
                }
            )
        for chip in chips.to_dict("records"):
            if chip["source_asset_id"] in known_wells:
                link_rows.append(
                    {
                        "source_asset_id": chip["source_asset_id"],
                        "observation_id": ids[f"naip:{chip['chip_id']}"],
                        "relationship_type": "IMAGE_COVERS",
                        "evidence_reference": "window centred on the reported registry coordinate",
                        "method_version": "gate6-naip-window-v1",
                        "provenance_class": "DERIVED",
                    }
                )
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO asset_observation_links (source_asset_id, observation_id, relationship_type,
                     evidence_reference, confidence, verification_status, method_version, provenance_class)
                   VALUES (%(source_asset_id)s, %(observation_id)s, %(relationship_type)s, %(evidence_reference)s,
                     NULL, 'UNVERIFIED', %(method_version)s, %(provenance_class)s)
                   ON CONFLICT DO NOTHING""",
                link_rows,
            )
        counts["links"] = len(link_rows)
        counts["links_skipped_unknown_well"] = len(links) + len(chips) - len(link_rows)

        reviews = ReviewLedger(root / GOLD / "reviews.jsonl").events()
        with conn.cursor() as cursor:
            for event in reviews:
                kind = "NAIP_CHIP" if event.evidence_id.startswith("CHIP-") else "PLUME"
                system = "naip" if kind == "NAIP_CHIP" else "carbon_mapper"
                cursor.execute(
                    """INSERT INTO inspection_review_events (review_id, evidence_id, evidence_kind, observation_id,
                         reviewer, outcome, visible_features, blinded_to_plume_status, supersedes, recorded_at, provenance_class)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'OBSERVED') ON CONFLICT DO NOTHING""",
                    (
                        event.review_id,
                        event.evidence_id,
                        kind,
                        ids[f"{system}:{event.evidence_id}"],
                        event.reviewer,
                        event.outcome.value,
                        [f.value for f in event.visible_features],
                        event.blinded_to_plume_status,
                        event.supersedes,
                        event.recorded_at,
                    ),
                )
        counts["reviews"] = len(reviews)

        requests_path = root / GOLD / "inspection_requests.json"
        requests = json.loads(requests_path.read_text()) if requests_path.exists() else []
        events = {r[0] for r in conn.execute("SELECT event_id FROM shared_events").fetchall()}
        loaded = 0
        with conn.cursor() as cursor:
            for request in requests:
                if request["trigger_event_id"] not in events:
                    continue
                cursor.execute(
                    """INSERT INTO inspection_requests (request_id, asset_id, affected_asset_id, scenario_id,
                         scenario_run_id, trigger_event_id, inspection_type, reason, status, created_at,
                         provenance_class)
                       VALUES (%(request_id)s, %(asset_id)s, %(affected_asset_id)s, %(scenario_id)s,
                         %(scenario_run_id)s, %(trigger_event_id)s, %(inspection_type)s, %(reason)s, %(status)s,
                         %(created_at)s, %(provenance_class)s) ON CONFLICT DO NOTHING""",
                    request,
                )
                loaded += 1
        counts["inspection_requests"] = loaded
        counts["inspection_requests_without_loaded_event"] = len(requests) - loaded
    counts["plume_observations"] = len(plumes)
    counts["image_observations"] = len(chips)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    with connect() as conn:
        print(json.dumps(load_inspection(conn, args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
