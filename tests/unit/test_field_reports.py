"""Generated reports and diagrams match the implementation."""

from __future__ import annotations

import pytest

from packages.scenario_engine.field_simulation import default_setup
from packages.scenario_engine.network_graph import asset_ids
from pipelines.synthetic.field_reports import (
    FOLDER,
    render_catalog,
    render_numerics,
    render_propagation,
    render_telemetry,
)
from tests.conftest import REPO_ROOT

DRAWIO = (REPO_ROOT / "docs/architecture.drawio").read_text()


@pytest.mark.parametrize(
    ("name", "render"),
    [
        ("scenario_catalog.md", render_catalog),
        ("synthetic_telemetry.md", render_telemetry),
        ("fault_propagation.md", render_propagation),
    ],
)
def test_report_matches_a_fresh_run(name, render):
    assert (FOLDER / name).read_text() == render(), "Run `make field-reports`."


def test_numerical_report_covers_every_scenario_and_shows_no_failure():
    body = render_numerics()
    for scenario in default_setup()[3].scenarios:
        assert scenario.scenario_id in body
    assert "| FAIL" not in body and " FAIL |" not in body
    for section in (
        "Agreement with an independent solver",
        "Regression against the Gate 3",
        "Edge cases",
    ):
        assert section in body


def test_committed_numerical_report_has_the_same_scenarios_and_no_failure():
    body = (FOLDER / "numerical_residuals.md").read_text()
    assert " FAIL |" not in body
    assert all(s.scenario_id in body for s in default_setup()[3].scenarios)


def test_every_report_discloses_synthetic_and_not_validated():
    for name in (
        "scenario_catalog",
        "synthetic_telemetry",
        "fault_propagation",
        "numerical_residuals",
        "provenance_validation",
    ):
        body = (FOLDER / f"{name}.md").read_text()
        assert "SYNTHETIC" in body and "not a validated engineering simulator" in body


def test_propagation_report_shows_every_prediction_matched():
    body = render_propagation()
    assert "81 of 81 topology-based predictions matched" in body


def test_diagram_pages_exist_and_name_every_network_asset():
    for page in ("aether-topology", "aether-network", "simulation-sequence"):
        assert f'<diagram id="{page}"' in DRAWIO
    network = DRAWIO[
        DRAWIO.index('<diagram id="aether-network"') : DRAWIO.index(
            '<diagram id="simulation-sequence"'
        )
    ]
    _, graph, _, _, _ = default_setup()
    for asset in set(asset_ids(graph)):
        assert asset in network, asset


def test_diagram_is_generated_from_the_current_configuration():
    import re

    from scripts.build_field_diagrams import (
        detection_page,
        network_page,
        sequence_page,
        topology_page,
    )

    for page in (topology_page(), network_page(), sequence_page(), detection_page()):
        stored = re.search(rf'  <diagram id="{page.page_id}".*?</diagram>\n', DRAWIO, re.S)
        assert stored and stored.group(0) == page.xml(), "Run scripts/build_field_diagrams.py."
