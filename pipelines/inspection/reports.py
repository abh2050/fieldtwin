"""Write the committed Gate 6 reports. Everything here is aggregate: no well, plume, or chip is named."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from packages.inspection.evidence import LIMITS
from packages.inspection.review import ReviewLedger, ReviewOutcome
from pipelines.acquire.common import core

from .associate import SILVER, load_rules
from .evidence import GOLD
from .wells import latest_batch

OUT = Path("reports") / "inspection"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _n(x: Any) -> str:
    return f"{int(x):,}"


def collect(root: Path) -> dict[str, Any]:
    silver = root / SILVER
    summary = json.loads((silver / "summary.json").read_text())
    links = pd.read_parquet(silver / "proximity_links.parquet")
    coverage = pd.read_parquet(silver / "coverage.parquet")
    cm = latest_batch(root, "carbon_mapper")
    naip = latest_batch(root, "naip")
    plumes = pd.read_parquet(root / "data/bronze/carbon_mapper" / cm["batch_id"] / "plumes.parquet")
    scenes = pd.read_parquet(root / "data/bronze/carbon_mapper" / cm["batch_id"] / "scenes.parquet")
    chips = pd.read_parquet(root / "data/bronze/naip" / naip["batch_id"] / "chips.parquet")
    nearest = links[links["rank"] == 1]["distance_m"]
    emissions = pd.to_numeric(plumes["emission_auto"], errors="coerce")
    reviews = ReviewLedger(root / GOLD / "reviews.jsonl")
    current = reviews.current()
    requests_path = root / GOLD / "inspection_requests.json"
    requests = json.loads(requests_path.read_text()) if requests_path.exists() else []
    cards = json.loads((root / GOLD / "evidence_cards.json").read_text())
    return {
        "rules_version": summary["rules_version"],
        "inputs": {**summary["inputs"], "naip_batch": naip["batch_id"]},
        "carbon_mapper": {
            "batch_id": cm["batch_id"],
            "retrieved": cm["ingestion_timestamp"],
            "checksum": cm["original_checksum"],
            "files": len(cm["files"]),
            "datasets": cm["datasets"],
            "plumes_by_instrument": plumes["instrument"].value_counts().sort_index().to_dict(),
            "plumes_by_year": plumes["scene_timestamp"]
            .str[:4]
            .value_counts()
            .sort_index()
            .to_dict(),
            "scenes_by_instrument": scenes["instrument"].value_counts().sort_index().to_dict(),
            "scenes_cloud_unknown": int(scenes["cloud_cover_pct"].isna().sum()),
            "emission_withheld": int((plumes["hide_emission"] == "True").sum()),
            "emission_kg_per_h_quartiles": [
                round(float(q), 1) for q in emissions.dropna().quantile([0.25, 0.5, 0.75])
            ],
            "sector_codes": plumes["sector"].fillna("none").value_counts().sort_index().to_dict(),
        },
        "naip": {
            "batch_id": naip["batch_id"],
            "retrieved": naip["ingestion_timestamp"],
            "checksum": naip["original_checksum"],
            "chips": len(chips),
            "by_group": chips["selection_group"].value_counts().sort_index().to_dict(),
            "acquisition_dates": chips["acquisition_date"].value_counts().sort_index().to_dict(),
            "gsd_m": sorted(chips["ground_sample_distance_m"].astype(float).unique().tolist()),
            "pixels": sorted(
                {f"{w}x{h}" for w, h in zip(chips["width_px"], chips["height_px"], strict=True)}
            ),
            "bytes": int(sum(f["size_bytes"] for f in naip["files"] if f["path"].endswith(".tif"))),
            "quarantined": naip["rejected_count"],
        },
        "association": {
            **{
                k: summary[k]
                for k in (
                    "wells",
                    "plumes",
                    "scenes",
                    "scenes_with_footprint",
                    "primary_radius_m",
                    "links",
                    "plumes_with_any_well_within_radius",
                    "wells_with_any_plume_within_radius",
                    "candidate_wells_per_linked_plume",
                    "sensitivity_links",
                    "proximity_vs_chance",
                    "coverage_status",
                )
            },
            "nearest_linked_distance_m_quartiles": [
                round(float(q), 1) for q in nearest.quantile([0.25, 0.5, 0.75])
            ],
            "wells_by_plumes_nearby": coverage[coverage["plumes_within_radius"] > 0][
                "plumes_within_radius"
            ].pipe(
                lambda s: {
                    "1": int((s == 1).sum()),
                    "2-4": int(((s >= 2) & (s <= 4)).sum()),
                    "5+": int((s >= 5).sum()),
                }
            ),
        },
        "review": {
            "cards": len(cards),
            "reviews_recorded": len(reviews.events()),
            "items_with_current_review": len(current),
            "outcomes": {
                o.value: sum(1 for e in current.values() if e.outcome is o) for o in ReviewOutcome
            },
            "inspection_requests": len(requests),
            "inspection_request_assets": sorted({r["asset_id"] for r in requests}),
        },
        "limits": list(LIMITS),
    }


def _table(rows: list[list[str]], header: list[str], align: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def write_reports(root: Path, data: dict[str, Any]) -> list[Path]:
    rules = load_rules(root)
    out = root / OUT
    (out / "results").mkdir(parents=True, exist_ok=True)
    cm, ni, a, rv = data["carbon_mapper"], data["naip"], data["association"], data["review"]
    written = []

    path = out / "results" / "gate6_summary.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")
    written.append(path)

    ds = cm["datasets"]
    ingestion = f"""# Aerial sources: acquisition

Generated by `pipelines/inspection/reports.py` from the batch manifests. Gate 6 adds two real sources. Both are **OBSERVED** and neither describes AETHER Field.

## Carbon Mapper

Batch `{cm["batch_id"]}`, retrieved {cm["retrieved"]}. Aggregate checksum `{cm["checksum"]}` over {cm["files"]} raw files.

| Dataset | Endpoint | Reported by source | Accepted | Quarantined |
|---|---|---:|---:|---:|
| Methane plumes | `catalog/plumes/annotated` | {ds["plumes"]["source_records"]} | {ds["plumes"]["accepted"]} | {ds["plumes"]["source_records"] - ds["plumes"]["accepted"]} |
| Scenes | `catalog/scenes/annotated` | {ds["scenes"]["source_records"]} | {ds["scenes"]["accepted"]} | {ds["scenes"]["source_records"] - ds["scenes"]["accepted"]} |

- **Study area:** the two Gate 1 townships (23S-28E and 24S-28E) widened by about 2 km, bounding box `{rules and core.load_yaml(root / "config/sources/carbon_mapper.yaml")["study_area"]["bbox"]}`.
- **Footprints:** {ds["scenes"]["with_footprint"]} of {ds["scenes"]["accepted"]} scenes got a polygon from {ds["footprint_tiles"]["tiles"]} public vector tiles at zoom {ds["footprint_tiles"]["zoom"]}. The scene list itself gives only bounding boxes. The tiles also hold {ds["footprint_tiles"]["tile_scenes_not_in_scene_list"]} scenes the scene list doesn't return; they are excluded, so coverage counts only listed scenes.
- **Quicklooks:** {ds["quicklooks"]} plume images, newest first. They stay in `data/raw/`.
- **Plumes by instrument:** {", ".join(f"{k} {v}" for k, v in cm["plumes_by_instrument"].items())}. By year: {", ".join(f"{k} {v}" for k, v in cm["plumes_by_year"].items())}.
- **Emission estimates:** kg/h as published. {cm["emission_withheld"]} plumes have the estimate withheld by Carbon Mapper and are stored without one. Quartiles of the rest: {", ".join(str(q) for q in cm["emission_kg_per_h_quartiles"])} kg/h. The API doesn't state what the uncertainty field represents, so it is recorded as `UNKNOWN`.
- **Sector codes:** {", ".join(f"{k} {v}" for k, v in cm["sector_codes"].items())}. These are Carbon Mapper's own IPCC sector codes, not facility attribution.
- **Scenes with unknown cloud cover:** {cm["scenes_cloud_unknown"]}. They never count as clear.

**Terms:** Carbon Mapper Terms of Use, effective 2026-01-13. A revocable, non-commercial license with attribution required; redistribution carries the same terms. Data by Carbon Mapper®. Source: Carbon Mapper (data.carbonmapper.org).

## USDA NAIP

Batch `{ni["batch_id"]}`, retrieved {ni["retrieved"]}. Aggregate checksum `{ni["checksum"]}`.

- **Chips:** {ni["chips"]} windows of {", ".join(ni["pixels"])} pixels at {", ".join(f"{g:g}" for g in ni["gsd_m"])} m, {ni["bytes"] / 1e6:.1f} MB in total. Groups: {", ".join(f"{k} {v}" for k, v in ni["by_group"].items())}. Quarantined: {ni["quarantined"]}.
- **Acquisition dates:** {", ".join(f"{k} ({v})" for k, v in ni["acquisition_dates"].items())}.
- **Access:** Microsoft Planetary Computer STAC, reading only each window from cloud-optimized GeoTIFFs. Access tokens are never stored.

**Terms:** not confirmed for 2022 imagery. NAIP is documented as public domain for imagery acquired through 2019; Planetary Computer lists the license as \"other\" with USDA FSA as licensor, and no primary USDA statement for 2022 was retrieved. Chips are therefore kept out of the repository. Access through Planetary Computer is subject to its terms of use. The imagery carries no emission, leak, or equipment-condition labels.

Neither source publishes checksums, so SHA-256 values prove only that files are unchanged since receipt.
"""
    path = root / "reports" / "ingestion" / "aerial_sources.md"
    path.write_text(ingestion)
    written.append(path)

    table = _table(
        [
            [
                f"{r['radius_m']:.0f} m",
                f"{r['plumes_within']} of {r['plumes']}",
                _pct(r["plume_share"]),
                _pct(r["chance_share"]),
                f"{100 * r['share_above_chance']:+.1f} points",
            ]
            for r in a["proximity_vs_chance"]
        ],
        ["Radius", "Plumes with a well inside", "Share", "Random points", "Above chance"],
        ["---", "---:", "---:", "---:", "---:"],
    )
    cand = a["candidate_wells_per_linked_plume"]
    first, last = a["proximity_vs_chance"][0], a["proximity_vs_chance"][-1]
    association = f"""# Spatial association: proximity, not attribution

Generated by `pipelines/inspection/reports.py`. Rules: `config/inspection/gate6_association.yaml`, version {data["rules_version"]}.

## What was compared

{a["plumes"]} Carbon Mapper methane plume origins against {a["wells"]["used"]} registry gas wells whose coordinates Gate 2 accepts for spatial analysis ({a["wells"]["registry"]} in the registry; {", ".join(f"{k} {v}" for k, v in a["wells"]["by_spatial_status"].items())}).

A plume and a well are linked as `EMISSION_NEAR` when the plume origin lies within {a["primary_radius_m"]:.0f} m of the well. Every link is `UNVERIFIED`, carries no confidence value, and is DERIVED. The database refuses to mark one verified or to turn it into `SOURCE_ATTRIBUTED_TO`.

**Disclosure:** the distribution of plume-to-well distances and a random-point baseline were looked at once, during source inspection, before the radius was fixed. The other radii are reported so the choice can be judged.

## Proximity against chance

How often a plume origin lies within each radius of any registry well, beside how often a uniformly random point in the study area does ({_n(rules["chance_baseline"]["points"])} points, seed {rules["chance_baseline"]["seed"]}).

{table}

Plume origins sit closer to registry wells than random points do. Relative to chance the difference is largest at {first["radius_m"]:.0f} m ({first["plume_share"] / first["chance_share"]:.1f} times the random share), and it has nearly vanished at {last["radius_m"]:.0f} m, where most of the study area is within reach of some well. This says plumes tend to occur where wells and their surrounding equipment are, not that any well is a source. Plumes repeat at persistent sources, so these shares are not independent trials and no interval is given for them.

## Why proximity can't name a source

- **Several candidates.** Of the {a["plumes_with_any_well_within_radius"]} plumes with a well within {a["primary_radius_m"]:.0f} m, {cand["one"]} have exactly one candidate, {cand["two_to_four"]} have two to four, and {cand["five_or_more"]} have five or more.
- **An incomplete registry.** The registry holds gas wells only. Oil wells, tank batteries, compressors, flares, and pipelines are absent, so the nearest registered well isn't necessarily the nearest infrastructure. One chip viewed during development shows a tank battery beside the registered pad; the chips have not otherwise been reviewed.
- **Uncertain locations.** Carbon Mapper states that plume representations may not precisely match infrastructure on the ground. OCD describes its well locations as approximate.
- **Wind and time.** A plume origin is an instantaneous estimate from one overpass.

Nearest-link distances among linked plumes, quartiles: {", ".join(f"{q:.0f}" for q in a["nearest_linked_distance_m_quartiles"])} m. Links at other radii: {", ".join(f"{k} m: {v}" for k, v in a["sensitivity_links"].items())}.

## What this supports

A statement of the form "a plume origin was detected N metres from this registered well, and K other registered wells are also within the radius." Nothing in Gate 6 supports a leak at a well, an emission source, an equipment condition, or any link to AETHER Field.
"""
    path = out / "spatial_association.md"
    path.write_text(association)
    written.append(path)

    status = a["coverage_status"]
    outcomes = ", ".join(f"{k} {v}" for k, v in rv["outcomes"].items())
    review = f"""# Coverage, evidence review, and inspection requests

Generated by `pipelines/inspection/reports.py`.

## Coverage

Each usable registry well, graded against Carbon Mapper scene footprints (cloud limit {rules["coverage"]["max_cloud_cover_pct"]}%, Carbon Mapper's own condition for a candidate null detect):

| Status | Wells | Meaning |
|---|---:|---|
| `PLUME_NEARBY` | {status.get("PLUME_NEARBY", 0)} | A plume origin within {a["primary_radius_m"]:.0f} m. Proximity only. |
| `IMAGED_NO_PLUME_NEARBY` | {status.get("IMAGED_NO_PLUME_NEARBY", 0)} | Inside a clear scene, with no plume origin within the radius. Not a clean bill of health: nothing exceeded the detection limit at those moments. |
| `IMAGED_CLOUDY_ONLY` | {status.get("IMAGED_CLOUDY_ONLY", 0)} | Only cloudy or unknown-cloud scenes. |
| `NOT_IMAGED` | {status.get("NOT_IMAGED", 0)} | No listed scene footprint contains it. |

Wells with plumes nearby, by number of plumes: {", ".join(f"{k}: {v}" for k, v in a["wells_by_plumes_nearby"].items())}.

## Evidence cards

{rv["cards"]} cards, one per well with a NAIP chip: {", ".join(f"{k} {v}" for k, v in data["naip"]["by_group"].items())}. Each card holds the coverage status, every plume within the radius with a proximity caption, the chip, attribution for both sources, and these fixed statements:

{chr(10).join(f"- {t}" for t in data["limits"])}

Every sentence on a card passes a claim guard (`packages/inspection/claims.py`) that rejects leak, cause, attribution, defect, certainty, drone, and AETHER claims unless negated. The rendered pages are checked again line by line. Pages are written to `data/gold/inspection/`, which is not committed, because they show real wells beside real plume records.

## Human review

Review is blinded: the queue shows each chip by an opaque ID, with nothing about plumes, so the reading of an image isn't steered by whether a plume was detected nearby. Outcomes are limited to {", ".join(f"`{o.value}`" for o in ReviewOutcome)}. None confirms a leak or names a source. Reviews are append-only; a correction supersedes, and the database enforces both.

**Reviews recorded: {rv["reviews_recorded"]}** ({rv["items_with_current_review"]} items with a current finding; {outcomes}). The workflow is built and tested, but no human has reviewed these images yet, and none were invented.

## Inspection requests

{rv["inspection_requests"]} request(s), for fictional assets {", ".join(rv["inspection_request_assets"]) or "none"}, generated from the stored AETHER-FAULT-001 prioritization input. Requests come only from synthetic AETHER events and can target only fictional assets; the database refuses a real well or a benchmark event. They carry no priority score, which is Gate 7's job. No request is ever generated for a real well.
"""
    path = out / "coverage_and_review.md"
    path.write_text(review)
    written.append(path)
    return written


def run(root: Path = core.REPO_ROOT) -> list[str]:
    data = collect(root)
    return [core.rel(p, root) for p in write_reports(root, data)]


if __name__ == "__main__":
    np.set_printoptions(precision=3)
    print(json.dumps(run(), indent=2))
