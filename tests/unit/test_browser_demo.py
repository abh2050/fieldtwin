"""The public browser bundle contains complete synthetic runs and no private source rows."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "apps/web/demo-public/demo"


def test_browser_bundle_is_complete_and_checksum_verified():
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["provenance_class"] == "SYNTHETIC"
    assert manifest["counts"] == {"assets": 47, "scenarios": 6, "runs": 6, "series": 234}
    assert {p.name for p in BUNDLE.iterdir()} == {*manifest["files"], "manifest.json"}
    for name, entry in manifest["files"].items():
        payload = (BUNDLE / name).read_bytes()
        assert len(payload) == entry["bytes"] < 1_000_000
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_browser_telemetry_keeps_every_sample_null_unit_and_quality_flag():
    snapshot = json.loads((BUNDLE / "snapshot.json").read_text())
    files = {}
    missing = 0
    for scenario in snapshot["scenarios"]:
        assert scenario["replay"] is None
        for run in scenario["runs"]:
            ref = snapshot["telemetry"][run["scenario_run_id"]]
            assert len(ref["tags"]["items"]) == 39
            for tag in ref["tags"]["items"]:
                filename = ref["files"][tag["tag"]]
                if filename not in files:
                    files[filename] = json.loads(gzip.decompress((BUNDLE / filename).read_bytes()))
                packed = files[filename]
                series = packed["series"][tag["tag"]]
                points = [dict(zip(packed["columns"], row, strict=True)) for row in series["rows"]]
                assert len(points) == run["sample_count"] == tag["value_count"] + tag["null_count"]
                assert sum(p["value"] is None for p in points) == tag["null_count"]
                assert all(p["unit"] == tag["unit_id"] for p in points)
                assert all(
                    p["quality"] and p["sensor_status"] and p["equipment_state"] for p in points
                )
                assert [p["offset_s"] for p in points] == [
                    i * run["sampling_interval_s"] for i in range(run["sample_count"])
                ]
                assert series["source"]["config_sha256"] == run["config_sha256"]
                assert "truth" not in series["source"]["path"]
                missing += tag["null_count"]
    assert missing > 0, "The communication-dropout scenario must retain gaps"


def test_browser_snapshot_excludes_public_rows_existing_decisions_and_reviews():
    text = (BUNDLE / "snapshot.json").read_text()
    snapshot = json.loads(text)
    assert all(
        a["is_fictional"] and a["provenance_class"] == "SYNTHETIC" for a in snapshot["assets"]
    )
    assert all(d["work_orders"] == [] for d in snapshot["details"].values())
    assert all(s["is_project_generated"] for s in snapshot["data_sources"])
    assert all(
        r["work_order_id"] is None and r["work_order_status"] is None
        for r in snapshot["recommendations"]
    )
    assert not re.search(r"\b30-\d{3}-\d{5}\b", text)
    for excluded in ("footprint_wgs84", "chip_url", "reviewer", "actor_kind", "fieldtwin.token"):
        assert f'"{excluded}"' not in text
    assert snapshot["reads"]["/api/v1/overview"]["work_order_backlog"] == []
    assert snapshot["reads"]["/api/v1/overview"]["decisions_by_actor_kind"] == []
    for value in snapshot["lineage"].values():
        assert value["lineage"]["observation"]["source_system_id"] == "aether_synthetic"
    for value in snapshot["reads"].values():
        if isinstance(value, dict) and "source" in value:
            source = value["source"]
            if isinstance(source, dict) and "sha256" in source:
                assert (
                    hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
                    == source["sha256"]
                )
