"""Gate 0: required repository structure and the fictional facility's constraints."""

import yaml

from tests.conftest import REPO_ROOT

FACILITY = yaml.safe_load((REPO_ROOT / "config/facility/aether_field.yaml").read_text())


def test_required_paths_exist():
    required = [
        "README.md", "CLAUDE.md", "AGENTS.md", "Makefile", "pyproject.toml", "package.json",
        ".env.example", ".gitignore", "docker-compose.yml", "docs/index.html",
        "docs/architecture.drawio", "scripts/bootstrap.sh", "scripts/validate.sh",
        "docs/product/charter.md", "docs/product/requirements.md",
        "docs/datasets/license_inventory.md", "infra/cost/cost_and_security_plan.md",
        "data_contracts/sources/nm_ocd.yaml", "data_contracts/sources/petrobras_3w.yaml",
        "data_contracts/sources/generated/nm_ocd.schema.json",
        "data_contracts/sources/generated/petrobras_3w.schema.json",
        "reports/data_quality/canonical_schema.md", "reports/data_quality/production_units.md",
        "reports/reconciliation/semantic_compatibility.md", "reports/gates/gate_2.md",
        "reports/reconciliation/entity_resolution.md", "reports/reconciliation/semantic_validation.md",
        "reports/reconciliation/geospatial_associations.md", "reports/scenarios/aether_fault_001.md",
        "reports/gates/gate_3.md", "docs/specification.md", "docs/product/synthetic_telemetry_spec.md",
        "config/scenarios/aether_fault_001.yaml",
        ".github/workflows/ci.yml",
    ]  # fmt: skip
    missing = [path for path in required if not (REPO_ROOT / path).exists()]
    assert not missing


def test_facility_is_marked_fictional_with_no_operator():
    assert FACILITY["facility"]["is_fictional"] is True
    assert FACILITY["facility"]["operator"] is None
    assert FACILITY["provenance_class"] == "SYNTHETIC"


def test_facility_meets_declared_constraints():
    assets, limits = FACILITY["assets"], FACILITY["constraints"]
    pads = assets["well_pads"]
    wells = [well for pad in pads for well in pad["wells"]]
    assert len(pads) == limits["well_pads"] == 2
    assert all(len(pad["wells"]) == limits["wells_per_pad"] == 6 for pad in pads)
    assert len(wells) == len(set(wells)) == limits["total_wells"] == 12
    assert len(assets["compression_station"]["compressors"]) == limits["compressors"] == 4


def test_aws_placeholders_refuse_rather_than_pretend():
    for name in ("aws_plan.sh", "aws_destroy.sh", "run_demo.sh"):
        assert "exit 2" in (REPO_ROOT / "scripts" / name).read_text()


def test_no_raw_data_can_be_committed():
    ignored = (REPO_ROOT / ".gitignore").read_text()
    assert "data/raw/*" in ignored and "data/bronze/*" in ignored and ".env" in ignored
