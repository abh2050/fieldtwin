"""Recorded hashes, run on every supported platform in CI."""

from __future__ import annotations

import pytest
import yaml

from packages.scenario_engine.field_simulation import default_setup, simulate_by_id
from tests.conftest import REPO_ROOT

EXPECTED = yaml.safe_load(
    (REPO_ROOT / "config/scenarios/aether_field_expected_hashes.yaml").read_text()
)


def test_every_scenario_has_a_recorded_hash():
    assert set(EXPECTED["hashes"]) == {s.scenario_id for s in default_setup()[3].scenarios}


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED["hashes"]))
def test_run_matches_the_recorded_hash(scenario_id):
    assert simulate_by_id(scenario_id).canonical_sha256() == EXPECTED["hashes"][scenario_id]
