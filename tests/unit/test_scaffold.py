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
        "config/facility/aether_network.yaml",
        "config/scenarios/aether_field_scenarios.yaml",
        "docs/product/field_simulation_spec.md",
        "reports/gates/gate_4.md",
        "reports/simulation/scenario_catalog.md",
        "reports/simulation/synthetic_telemetry.md",
        "reports/simulation/numerical_residuals.md",
        "reports/simulation/fault_propagation.md",
        "reports/simulation/provenance_validation.md",
        "reports/simulation/diagrams/aether_asset_topology.png",
        "reports/simulation/diagrams/aether_physical_network.png",
        "reports/simulation/diagrams/simulation_sequence.png",
        "config/experiments/gate5_evaluation.yaml",
        "config/experiments/aether_benchmark.yaml",
        "docs/adr/0017-detection-evaluation-design.md",
        "reports/gates/gate_5.md",
        "reports/experiments/3w_label_audit.md",
        "reports/experiments/3w_benchmark.md",
        "reports/experiments/aether_synthetic_benchmark.md",
        "reports/experiments/model_comparison.md",
        "reports/experiments/robustness.md",
        "reports/experiments/inference_performance.md",
        "reports/experiments/detection_evaluation.png",
        "reports/simulation/reliability_stress.md",
        "config/sources/carbon_mapper.yaml",
        "config/sources/naip.yaml",
        "config/inspection/gate6_association.yaml",
        "data_contracts/sources/carbon_mapper.yaml",
        "data_contracts/sources/naip.yaml",
        "db/migrations/0014_aerial_evidence.sql",
        "docs/adr/0018-aerial-evidence-as-proximity.md",
        "reports/gates/gate_6.md",
        "reports/ingestion/aerial_sources.md",
        "reports/inspection/spatial_association.md",
        "reports/inspection/coverage_and_review.md",
        "reports/inspection/results/gate6_summary.json",
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
