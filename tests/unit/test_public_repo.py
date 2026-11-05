"""What this public repository must not contain, and documents that must match the implementation."""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml

from packages.scenario_engine.config import load_config
from pipelines.synthetic.report import REPORT, render
from tests.conftest import REPO_ROOT

BINARY = {".parquet", ".zip", ".lock", ".png", ".xlsx"}
THIS_FILE = "tests/unit/test_public_repo.py"
# Built from parts, so this file doesn't match its own patterns.
PERSONAL_PATHS = ["/Us" + "ers/", "/var/fo" + "lders/", "/priv" + "ate/tmp/"]
PERSONAL_NAMES = ["abhi" + "shek", "gma" + "il.com"]
AWS_SPECIFIC = ["aws" + "new", "us-ea" + "st-1", "us-we" + "st-2"]
CONVERSATIONAL = [
    "Claude Code System" + " Prompt",
    "SYSTEM" + " PROMPT",
    "favi" + "cons",
    "I recom" + "mend",
]


def tracked_files():
    output = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in output.stdout.splitlines() if (REPO_ROOT / p).is_file()]


def text_files():
    for relative in tracked_files():
        path = REPO_ROOT / relative
        if path.suffix not in BINARY and relative != THIS_FILE:
            yield relative, path.read_text(errors="ignore")


@pytest.mark.parametrize(
    ("label", "needles"),
    [
        ("personal path", PERSONAL_PATHS),
        ("personal name", PERSONAL_NAMES),
        ("AWS specific", AWS_SPECIFIC),
        ("conversational note", CONVERSATIONAL),
    ],
)
def test_public_files_have_no_private_or_conversational_content(label, needles):
    found = [(path, n) for path, body in text_files() for n in needles if n in body]
    assert found == [], label


def test_no_real_ocd_api_number_is_published():
    """Hand-written fixture rows use the 9xxxx range. Anything else could be a real well."""
    pattern = re.compile(r"\b30-\d{3}-\d{5}\b")
    found = [
        (path, match)
        for path, body in text_files()
        for match in pattern.findall(body)
        if not match.startswith("30-015-9")
    ]
    assert found == []


def test_no_individual_well_appears_in_generated_reports():
    for path, body in text_files():
        if path.startswith("reports/") and path != "reports/gates/gate_3_execution_log.txt":
            assert "nm_ocd:well:" not in body, path


def test_raw_and_restricted_data_stay_ignored():
    ignored = (REPO_ROOT / ".gitignore").read_text()
    for pattern in ("data/raw/*", "data/bronze/*", "data/gold/*", "data/fixtures_local/", ".env"):
        assert pattern in ignored
    leaked = [
        p
        for p in tracked_files()
        if re.match(r"data/(raw|bronze|silver|gold|fixtures_local)/", p)
        and not p.endswith("README.md")
    ]
    assert leaked == []


def test_parquet_files_exist_only_in_fixtures():
    assert [
        p for p in tracked_files() if p.endswith(".parquet") and not p.startswith("data/fixtures/")
    ] == []


def test_no_large_files_are_tracked():
    assert [p for p in tracked_files() if (REPO_ROOT / p).stat().st_size > 1_000_000] == []


def test_env_example_holds_only_placeholders():
    body = (REPO_ROOT / ".env.example").read_text()
    assert "AWS_PROFILE=your-aws-profile" in body
    assert "AWS_REGION=your-aws-region" in body


# Specification


def section_22(text):
    start = text.index("# 22. REPRODUCIBLE DEMONSTRATION")
    return text[start:].split("\n---", 1)[0].strip()


SPEC = (REPO_ROOT / "docs/specification.md").read_text()
INSTRUCTIONS = (REPO_ROOT / "instructions.md").read_text()


def test_section_22_is_the_same_in_both_documents():
    assert section_22(SPEC) == section_22(INSTRUCTIONS)


def test_section_22_defines_the_synthetic_restriction_scenario():
    section = section_22(SPEC)
    assert "Progressive Gathering-Line Restriction" in section
    assert "Select fictional Well A-03" in section
    assert "does not replay Petrobras 3W" in section
    assert "Replay the event" not in section
    assert "Select a source-verified Petrobras event" not in section


def test_specification_no_longer_describes_3w_replay_into_aether():
    assert "Replay a compatible Petrobras 3W event" not in SPEC
    assert "Replay the event against" not in SPEC


# Documents match the implementation


def test_scenario_report_matches_a_fresh_run():
    assert REPORT.read_text() == render(load_config()), "Run `make gate3-reports`."


def test_scenario_config_targets_declared_fictional_assets():
    config = load_config()
    facility = yaml.safe_load((REPO_ROOT / "config/facility/aether_field.yaml").read_text())
    wells = [w for pad in facility["assets"]["well_pads"] for w in pad["wells"]]
    assert config.scenario.target_well == "A-03" and "A-03" in wells
    segments = facility["assets"]["gathering_network"]["gathering_segments"]
    assert config.scenario.restricted_segment in segments
    connections = {(c["source"], c["target"]) for c in facility["flow_connections"]}
    assert ("A-03", "GS-A") in connections


def test_sensors_use_only_declared_measurement_definitions():
    reference = yaml.safe_load(
        (REPO_ROOT / "data_contracts/semantic_mappings/reference_data.yaml").read_text()
    )
    declared = {
        m["id"]: m
        for m in reference["aether_measurements"] + reference["aether_gathering_measurements"]
    }
    for sensor in load_config().sensors:
        definition = declared[sensor.measurement_definition_id]
        assert definition["reference"] == sensor.reference
        assert definition["unit"] == sensor.unit
        assert definition["quantity"] == sensor.quantity


def test_telemetry_spec_lists_every_declared_invariant():
    spec = (REPO_ROOT / "docs/product/synthetic_telemetry_spec.md").read_text()
    for name in load_config().expected_invariants:
        assert f"`{name}`" in spec


def test_python_flow_rules_match_the_database_migration():
    from packages.reconciliation.scenario import ALLOWED_FLOW_CONNECTIONS

    migration = (REPO_ROOT / "db/migrations/0011_domain_boundaries.sql").read_text()
    rules = set(re.findall(r"\('([A-Z_]+)', '([A-Z_]+)', '([A-Z_]+)',", migration))
    assert rules == ALLOWED_FLOW_CONNECTIONS
