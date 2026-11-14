"""Export existing synthetic network runs for the explicit browser demo (ADR 0023).

Run after the local Gates 4, 5, 7, and application data are built:
    PYTHONPATH=.:apps/api/src uv run python scripts/export_browser_demo.py

This reads through the same fieldtwin_app path as the API. No failed acquisition is substituted,
no experiment runs, no database writes occur, and public source rows are never exported.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient
from fieldtwin_api.db import _connect
from fieldtwin_api.main import create_app
from fieldtwin_api.routers.scenarios import SERIES_COLUMNS
from fieldtwin_api.settings import DISCLOSURE, load_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps/web/demo-public/demo"


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def export() -> None:
    config = load_settings()
    logging.disable(logging.INFO)
    with tempfile.TemporaryDirectory(prefix="fieldtwin-browser-demo-") as tmp:
        target = Path(tmp)
        files: dict[str, dict[str, object]] = {}

        def write(name: str, value: object, compressed: bool = False) -> None:
            raw = encode(value)
            payload = gzip.compress(raw, mtime=0) if compressed else raw
            (target / name).write_bytes(payload)
            files[name] = {
                "sha256": digest(payload),
                "bytes": len(payload),
                "encoding": "gzip" if compressed else "json",
            }

        with TestClient(create_app(config)) as client:

            def get(path: str):
                response = client.get(path)
                response.raise_for_status()
                return response.json()

            health = get("/health")
            assert health["checks"]["role"] == "fieldtwin_app"
            assets = get("/api/v1/assets?limit=500")["items"]
            assert len(assets) == 47 and all(
                a["is_fictional"] and a["provenance_class"] == "SYNTHETIC" for a in assets
            ), "Only the declared synthetic facility may be exported"
            scenarios = get("/api/v1/scenarios")["items"]
            scenarios = [
                s for s in scenarios if any("aether_field/" in r["output_uri"] for r in s["runs"])
            ]
            assert len(scenarios) == 6, "Build all six network scenarios before export"
            run_ids = set()
            telemetry = {}
            for scenario in scenarios:
                scenario["replay"] = None
                scenario["runs"] = [
                    r for r in scenario["runs"] if "aether_field/" in r["output_uri"]
                ]
                for run in scenario["runs"]:
                    assert run["provenance_class"] == "SYNTHETIC"
                    run_id = run["scenario_run_id"]
                    run_ids.add(run_id)
                    # output_sha256 is the simulator's canonical truth+telemetry hash, not a file hash.
                    file_sha = digest((config.repo_root / run["output_uri"]).read_bytes())
                    prefix = (
                        f"/api/v1/scenarios/{quote(scenario['scenario_id'])}/runs/{quote(run_id)}"
                    )
                    tags = get(f"{prefix}/tags")
                    series = {}
                    for tag in tags["items"]:
                        data = get(f"{prefix}/telemetry?tag={quote(tag['tag'])}")
                        assert data["provenance_class"] == "SYNTHETIC"
                        points = data.pop("points")
                        assert len(points) == tag["value_count"] + tag["null_count"]
                        series[tag["tag"]] = {
                            **data,
                            "rows": [[p[c] for c in SERIES_COLUMNS] for p in points],
                        }
                    by_tag = {}
                    names = list(series)
                    for start in range(0, len(names), 13):
                        group = names[start : start + 13]
                        filename = f"{scenario['scenario_id'].lower()}-{start // 13 + 1}.bin"
                        write(
                            filename,
                            {
                                "columns": SERIES_COLUMNS,
                                "series": {name: series[name] for name in group},
                            },
                            compressed=True,
                        )
                        by_tag.update({name: filename for name in group})
                    telemetry[run_id] = {
                        "files": by_tag,
                        "tags": tags,
                        "telemetry_file_sha256": file_sha,
                    }
                    print(f"Exported {run_id}: {len(series)} complete sensor series", flush=True)

            details, relationships, observations, lineage = {}, {}, {}, {}
            for asset in assets:
                key = asset["asset_id"]
                prefix = f"/api/v1/assets/{quote(key)}"
                details[key] = get(prefix)
                details[key]["work_orders"] = []
                relationships[key] = get(f"{prefix}/relationships")
                observations[key] = [
                    o
                    for o in get(f"{prefix}/observations?limit=500")["items"]
                    if o["scenario_run_id"] in run_ids
                ]
                for obs in observations[key]:
                    assert obs["provenance_class"] == "SYNTHETIC"
                    record = f"observation:{obs['observation_id']}"
                    lineage[record] = get(f"/api/v1/lineage/{record}")
                    assert (
                        lineage[record]["lineage"]["observation"]["source_system_id"]
                        == "aether_synthetic"
                    )

            recommendations = get("/api/v1/recommendations?limit=500")["items"]
            recommendations = [r for r in recommendations if r["scenario_run_id"] in run_ids]
            for rec in recommendations:
                rec["work_order_id"] = rec["work_order_status"] = None
                assert sum(t["points"] for t in rec["terms"]) == rec["priority_score"]
            alarms = [
                a
                for a in get("/api/v1/anomalies?limit=500")["items"]
                if a["scenario_run_id"] in run_ids
            ]
            with _connect(config, read_only=True) as conn:
                requests = conn.execute("""SELECT request_id, asset_id, affected_asset_id, scenario_id,
                    scenario_run_id, inspection_type, reason, status, created_at::text,
                    provenance_class::text FROM inspection_requests ORDER BY request_id""").fetchall()
            requests = [r for r in requests if r["scenario_run_id"] in run_ids]
            assert all(r["provenance_class"] == "SYNTHETIC" for r in requests)
            sources = get("/api/v1/data-sources")["items"]
            sources = [s for s in sources if s["source_system_id"] == "aether_synthetic"]
            for source in sources:
                assert source["is_project_generated"]
                source["observations"] = sum(len(v) for v in observations.values())
            batches = get("/api/v1/ingestion-runs?source_system_id=aether_synthetic&limit=500")[
                "items"
            ]
            quality = get("/api/v1/data-quality?source_system_id=aether_synthetic&limit=500")
            assert quality["total"] == len(quality["items"])
            reads = {
                path: get(path)
                for path in [
                    "/api/v1/overview",
                    "/api/v1/network",
                    "/api/v1/model-evaluations",
                    "/api/v1/economics/comparison",
                    "/api/v1/diagnostics/d1",
                    "/api/v1/reports",
                ]
            }
            assert reads["/api/v1/overview"]["detection"] is not None
            assert reads["/api/v1/overview"]["economics"] is not None
            for report in reads["/api/v1/reports"]["items"]:
                assert report["available"], report["path"]
                reads[f"/api/v1/reports/{report['slug']}"] = get(
                    f"/api/v1/reports/{report['slug']}"
                )
            counts = reads["/api/v1/overview"]["counts"]
            counts.update(
                fictional_assets=len(assets),
                scenarios=len(scenarios),
                scenario_runs=len(run_ids),
                alarms=len(alarms),
                real_sources=0,
                dispatching_recommendations=sum(
                    r["action"] in {"FIELD_INSPECTION", "CHECK_INSTRUMENTATION"}
                    for r in recommendations
                ),
                pending_inspections=sum(r["status"] == "REQUESTED" for r in requests),
                open_quality_exceptions=sum(q["status"] == "OPEN" for q in quality["items"]),
            )
            reads["/api/v1/overview"]["work_order_backlog"] = []
            reads["/api/v1/overview"]["decisions_by_actor_kind"] = []
            snapshot = {
                "schema_version": 1,
                "disclosure": DISCLOSURE,
                "assets": assets,
                "details": details,
                "relationships": relationships,
                "observations": observations,
                "lineage": lineage,
                "scenarios": scenarios,
                "recommendations": recommendations,
                "alarms": alarms,
                "inspection_requests": requests,
                "data_sources": sources,
                "ingestion_runs": batches,
                "quality": quality,
                "reads": reads,
                "telemetry": telemetry,
            }
            # Synthetic-only payload and aggregate reports: never publish OCD rows/identifiers.
            encoded = encode(snapshot)
            assert not re.search(rb"30-0(?:15|25)-\d{5}", encoded)
            assert b"footprint_wgs84" not in encoded and b"chip_url" not in encoded
            write("snapshot.json", snapshot)
            manifest = {
                "schema_version": 1,
                "provenance_class": "SYNTHETIC",
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "exporter": "scripts/export_browser_demo.py",
                "files": files,
                "counts": {
                    "assets": len(assets),
                    "scenarios": len(scenarios),
                    "runs": len(run_ids),
                    "series": sum(len(t["tags"]["items"]) for t in telemetry.values()),
                },
                "omitted": [
                    "Public source rows and aerial pixels",
                    "Evidence cards and reviews",
                    "Existing work orders, approvals and audit events",
                    "Tokens and simulator truth files",
                ],
                "telemetry_encoding": "Lossless columnar JSON + gzip; no downsampling or imputation.",
            }
            (target / "manifest.json").write_bytes(encode(manifest))
        OUT.mkdir(parents=True, exist_ok=True)
        for old in OUT.glob("*.bin"):
            if old.name not in files:
                old.unlink()
        for path in target.iterdir():
            assert path.stat().st_size < 1_000_000, f"Split oversized demo file: {path.name}"
            (OUT / path.name).write_bytes(path.read_bytes())
        print(f"Wrote {sum(p.stat().st_size for p in target.iterdir()):,} bytes to {OUT}")


if __name__ == "__main__":
    export()
