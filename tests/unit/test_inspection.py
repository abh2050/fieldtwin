"""Gate 6 evidence logic. Coordinates below are test inputs placed at known distances, not datasets;
source parsing is tested on records cut from the real downloads (data/fixtures)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pydantic
import pytest
from shapely.geometry import box

from packages.domain.events import EventKind, PrioritizationInput
from packages.inspection import claims
from packages.inspection.association import (
    Points,
    nearest_distance_m,
    proximity_links,
    proximity_table,
    random_points,
)
from packages.inspection.contracts import CoverageStatus, ImageChip, ProximityLink, WellCoverage
from packages.inspection.coverage import Scene, well_coverage
from packages.inspection.evidence import LIMITS, build_card
from packages.inspection.geodesy import EARTH_RADIUS_M, haversine_m
from packages.inspection.requests import NotAFictionalAsset, request_from_event
from packages.inspection.review import (
    ReviewError,
    ReviewEvent,
    ReviewLedger,
    ReviewOutcome,
    VisibleFeature,
)
from pipelines.inspection.evidence import check_rendered

LAT0, LON0 = 32.25, -104.08
M_PER_DEG_LAT = np.pi * EARTH_RADIUS_M / 180


def north(metres: float) -> float:
    return LAT0 + metres / M_PER_DEG_LAT


# Geometry


def test_haversine_matches_one_degree_of_latitude():
    assert haversine_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(M_PER_DEG_LAT, rel=1e-9)
    assert haversine_m(LAT0, LON0, LAT0, LON0) == 0.0


def test_points_reject_duplicate_ids_and_ragged_input():
    with pytest.raises(ValueError):
        Points.of(["a", "a"], [1, 2], [1, 2])
    with pytest.raises(ValueError):
        Points.of(["a"], [1, 2], [1])


# Proximity


def _wells(*offsets: tuple[str, float]) -> Points:
    return Points.of([w for w, _ in offsets], [north(m) for _, m in offsets], [LON0] * len(offsets))


def test_links_rank_every_well_inside_the_radius_and_skip_the_rest():
    plumes = Points.of(["p"], [LAT0], [LON0])
    wells = _wells(("w-far", 400.0), ("w-near", 50.0), ("w-mid", 200.0))
    links = proximity_links(plumes, wells, 250.0)
    assert [(k.source_asset_id, k.rank) for k in links] == [("w-near", 1), ("w-mid", 2)]
    assert {k.candidates_within_radius for k in links} == {2}
    assert links[0].distance_m == pytest.approx(50.0, abs=0.2)


def test_radius_boundary_is_inclusive_and_ties_break_by_well_id():
    plumes = Points.of(["p"], [LAT0], [LON0])
    wells = _wells(("w-b", 100.0), ("w-a", 100.0))
    links = proximity_links(plumes, wells, 100.0 + 1e-6)
    assert [k.source_asset_id for k in links] == ["w-a", "w-b"]


def test_links_are_proximity_only_and_cannot_be_promoted():
    link = proximity_links(Points.of(["p"], [LAT0], [LON0]), _wells(("w", 10.0)), 250.0)[0]
    assert link.relationship_type == "EMISSION_NEAR"
    assert link.verification_status == "UNVERIFIED"
    assert link.confidence is None
    data = link.model_dump()
    for change in (
        {"relationship_type": "SOURCE_ATTRIBUTED_TO"},
        {"verification_status": "VERIFIED"},
        {"confidence": 0.9},
        {"source_well": "w"},
    ):
        with pytest.raises(pydantic.ValidationError):
            ProximityLink(**{**data, **change})


def test_geometric_reference_compares_plumes_with_box_points():
    wells = _wells(("w", 0.0))
    plumes = Points.of(["a", "b"], [north(10), north(500)], [LON0, LON0])
    baseline = Points.of(
        ["r1", "r2", "r3", "r4"], [north(50), north(300), north(800), north(900)], [LON0] * 4
    )
    rows = {r["radius_m"]: r for r in proximity_table(plumes, wells, baseline, [100, 600])}
    assert rows[100.0]["plume_share"] == 0.5 and rows[100.0]["reference_share"] == 0.25
    assert rows[600.0]["reference_share"] == 0.5


def test_matched_null_draws_inside_each_plumes_own_footprint():
    from packages.inspection.association import (
        first_of_each_group,
        location_groups,
        matched_null,
        matched_table,
        sample_in_polygon,
    )

    footprint = box(LON0 - 0.01, LAT0 - 0.01, LON0 + 0.01, LAT0 + 0.01)
    lat, lon = sample_in_polygon(footprint, 500, np.random.default_rng(1))
    assert len(lat) == 500 and footprint.bounds[0] <= lon.min() and lon.max() <= footprint.bounds[2]

    # A well at the centre of one scene and far from the other: the null shares follow the scene.
    far = box(LON0 + 0.5, LAT0, LON0 + 0.52, LAT0 + 0.02)
    wells = _wells(("w", 0.0))
    plumes = Points.of(["p1", "p2"], [LAT0, LAT0 + 0.01], [LON0, LON0 + 0.51])
    null = matched_null(plumes, ["s1", "s2"], {"s1": footprint, "s2": far}, wells, 300, 3)
    assert null.null_distance_m.shape == (2, 300)
    assert null.null_distance_m[1].min() > 40_000
    rows = {r["radius_m"]: r for r in matched_table(null, [1000], 200, 3)}
    assert rows[1000.0]["plume_share"] == 0.5 and rows[1000.0]["scenes"] == 2
    assert 0 < rows[1000.0]["matched_null_share"] < 0.5

    grouped = Points.of(["a", "b", "c"], [LAT0, north(50), north(5000)], [LON0] * 3)
    labels = location_groups(grouped, 100)
    assert labels[0] == labels[1] != labels[2]
    trio = matched_null(grouped, ["s1"] * 3, {"s1": footprint}, wells, 10, 1)
    assert len(first_of_each_group(trio, labels, ["2024", "2020", "2021"]).plume_scene) == 2


def test_random_points_are_reproducible_and_inside_the_box():
    bbox = [-104.155, 32.149, -104.012, 32.360]
    a, b = random_points(bbox, 500, 7), random_points(bbox, 500, 7)
    assert np.array_equal(a.lat, b.lat)
    assert a.lon.min() >= bbox[0] and a.lon.max() <= bbox[2]
    assert a.lat.min() >= bbox[1] and a.lat.max() <= bbox[3]


def test_nearest_distance_with_no_wells_is_infinite():
    assert np.isinf(
        nearest_distance_m(Points.of(["p"], [LAT0], [LON0]), Points.of([], [], []))
    ).all()


# Coverage


def _scene(uuid: str, cloud: float | None, footprint) -> Scene:
    return Scene(
        uuid, datetime(2024, 5, 1, tzinfo=UTC), cloud, (-105.0, 31.0, -103.0, 33.0), footprint
    )


def test_coverage_grades_each_well():
    wells = Points.of(
        ["inside", "cloudy", "outside", "near"],
        [32.25, 32.75, 31.5, 32.30],
        [-104.1, -104.1, -104.1, -104.1],
    )
    clear = box(-104.5, 32.0, -103.9, 32.5).wkt
    cloudy = box(-104.5, 32.6, -103.9, 32.9).wkt
    scenes = [_scene("s1", 10.0, clear), _scene("s2", 80.0, cloudy), _scene("s3", None, clear)]
    link = proximity_links(
        Points.of(["p"], [32.30], [-104.1]), Points.of(["near"], [32.30], [-104.1]), 250
    )
    result = {c.source_asset_id: c for c in well_coverage(wells, scenes, link, 25)}
    assert result["inside"].status is CoverageStatus.IMAGED_NO_PLUME_NEARBY
    assert (
        result["inside"].clear_scenes_in_footprint == 1
    )  # unknown cloud cover never counts as clear
    assert result["cloudy"].status is CoverageStatus.IMAGED_CLOUDY_ONLY
    assert result["outside"].status is CoverageStatus.NOT_IMAGED
    assert result["near"].status is CoverageStatus.PLUME_NEARBY


def test_scene_without_footprint_never_counts_as_coverage():
    wells = Points.of(["w"], [32.25], [-104.1])
    [result] = well_coverage(wells, [_scene("s", 0.0, None)], [], 25)
    assert result.status is CoverageStatus.NOT_IMAGED
    assert result.scenes_without_footprint_in_bounds == 1


# Claim guard


@pytest.mark.parametrize(
    "text",
    [
        "Methane leak at this well.",
        "The plume was emitted by this well.",
        "Plume attributed to well 30-015-1.",
        "This well is the source.",
        "Wellhead appears damaged.",
        "Confirmed emission.",
        "Drone image of the pad.",
        "Evidence for AETHER well A-03.",
        "This well released methane.",
        "The pad is venting gas.",
        "Methane escaping from the tank battery.",
        "The flare emits methane.",
        "Gas discharged near the wellhead.",
    ],
)
def test_guard_rejects_unsupported_claims(text):
    with pytest.raises(claims.UnsupportedClaim):
        claims.check(text)


@pytest.mark.parametrize(
    "text", [*LIMITS, "This is not source attribution.", "Cannot confirm a leak."]
)
def test_guard_allows_negated_and_limiting_statements(text):
    assert claims.check(text) == text


def test_synthetic_text_may_name_fictional_faults_but_never_a_leak():
    assert claims.check("AETHER-FAULT-001 on simulated asset FL-A-03.", synthetic=True)
    with pytest.raises(claims.UnsupportedClaim):
        claims.check("AETHER-FAULT-001 on simulated asset FL-A-03.")
    with pytest.raises(claims.UnsupportedClaim):
        claims.check("Leak on simulated asset A-03.", synthetic=True)


def test_rendered_page_check_reads_visible_text_only():
    assert check_rendered("<p>No plume origin within 250 m</p><img alt='x' src='leak.png'>") == 1
    with pytest.raises(claims.UnsupportedClaim):
        check_rendered("<p>Leak confirmed</p>")


# Evidence card


def _chip() -> ImageChip:
    return ImageChip(
        chip_id="CHIP-1",
        source_asset_id="w",
        stac_item_id="item",
        acquisition_date=date(2022, 5, 30),
        ground_sample_distance_m=0.6,
        crs="EPSG:26913",
        footprint_wgs84=(-104.1, 32.2, -104.0, 32.3),
        source_href="https://example.invalid/x.tif",
        path="x.tif",
        sha256="0" * 64,
        width_px=500,
        height_px=500,
        bands=4,
        selection_group="CONTROL",
    )


def test_card_carries_attribution_limits_and_proximity_captions():
    wells = _wells(("w", 0.0), ("w2", 120.0))
    links = proximity_links(Points.of(["p"], [north(30)], [LON0]), wells, 250.0)
    coverage = WellCoverage(
        source_asset_id="w",
        scenes_in_footprint=1,
        clear_scenes_in_footprint=1,
        scenes_without_footprint_in_bounds=0,
        plumes_within_radius=1,
        first_clear_scene=None,
        last_clear_scene=None,
        status=CoverageStatus.PLUME_NEARBY,
    )
    details = {
        "p": {
            "observed_at": datetime(2024, 5, 1, tzinfo=UTC),
            "instrument": "tan",
            "emission_kg_per_h": None,
            "emission_uncertainty_kg_per_h": None,
        }
    }
    card = build_card(
        coverage, [k for k in links if k.source_asset_id == "w"], details, _chip(), 250.0
    )
    assert card.limits == list(LIMITS)
    assert any("Carbon Mapper" in a for a in card.attributions) and any(
        "NAIP" in a for a in card.attributions
    )
    assert "1 other registered well is also within the radius" in card.plumes[0].caption
    assert "not source attribution" in card.plumes[0].caption
    assert card.plumes[0].uncertainty_definition == "UNKNOWN"
    for text in card.all_text():
        claims.check(text)
    assert not {"source", "attributed_to", "leak", "cause"} & set(type(card).model_fields)


# Review ledger


def _review(**overrides) -> ReviewEvent:
    base = {
        "evidence_id": "CHIP-1",
        "reviewer": "reviewer-a",
        "outcome": ReviewOutcome.INFRASTRUCTURE_VISIBLE,
        "blinded_to_plume_status": True,
    }
    return ReviewEvent(**{**base, **overrides})


def test_ledger_is_append_only_with_one_supersession(tmp_path: Path):
    ledger = ReviewLedger(tmp_path / "reviews.jsonl")
    first = ledger.append(_review())
    with pytest.raises(ReviewError):
        ledger.append(first)
    second = ledger.append(
        _review(outcome=ReviewOutcome.IMAGE_UNUSABLE, supersedes=first.review_id)
    )
    assert ledger.current()["CHIP-1"].review_id == second.review_id
    assert len(ledger.history("CHIP-1")) == 2
    with pytest.raises(ReviewError):
        ledger.append(_review(supersedes=first.review_id))
    with pytest.raises(ReviewError):
        ledger.append(_review(evidence_id="CHIP-2", supersedes=second.review_id))
    with pytest.raises(ReviewError):
        ledger.append(_review(supersedes="missing"))


def test_review_cannot_confirm_a_leak_or_name_a_source():
    assert not {o.value for o in ReviewOutcome} & {
        "LEAK_CONFIRMED",
        "SOURCE_IDENTIFIED",
        "DEFECT_FOUND",
    }
    with pytest.raises(pydantic.ValidationError):
        _review(reviewer="")
    features = (VisibleFeature.WELL_PAD, VisibleFeature.TANK_BATTERY)
    assert _review(visible_features=features).visible_features == tuple(sorted(features))
    with pytest.raises(pydantic.ValidationError):
        _review(visible_features=(VisibleFeature.WELL_PAD, VisibleFeature.WELL_PAD))
    with pytest.raises(pydantic.ValidationError):
        _review(visible_features=("METHANE_LEAK",))


def test_reviews_hold_no_free_text_and_are_always_blind():
    with pytest.raises(pydantic.ValidationError):
        _review(note="Tank battery visible north of the pad.")
    with pytest.raises(pydantic.ValidationError):
        _review(blinded_to_plume_status=False)
    assert _review().blinded_to_plume_status is True
    text_fields = {
        name
        for name, field in ReviewEvent.model_fields.items()
        if field.annotation in (str, "str")
        and name not in {"review_id", "evidence_id", "reviewer", "supersedes"}
    }
    assert not text_fields


# Inspection requests


def _prioritization(asset: str = "A-03", affected: str = "GS-A") -> PrioritizationInput:
    return PrioritizationInput(
        event_id="AETHER-FAULT-001:v1:fault:integration-rule",
        scenario_id="AETHER-FAULT-001",
        scenario_run_id="AETHER-FAULT-001:v1:fault",
        asset_id=asset,
        affected_asset_id=affected,
        event_kind=EventKind.INTEGRATION_PROOF_RULE,
        evidence={"sensor": "dpt_pa"},
        disclosure="Synthetic telemetry from a simplified physical model of a fictional well.",
    )


def test_request_targets_fictional_assets_and_is_deterministic():
    fictional = {"A-03", "GS-A"}
    a = request_from_event(_prioritization(), fictional)
    b = request_from_event(_prioritization(), fictional)
    assert (
        a.request_id == b.request_id
        and a.provenance_class == "SYNTHETIC"
        and a.priority_score is None
    )
    with pytest.raises(NotAFictionalAsset):
        request_from_event(_prioritization(asset="nm_ocd:well:30-015-90001"), fictional)


def test_fictional_asset_list_covers_the_facility_hierarchy():
    from pipelines.inspection.requests import fictional_asset_ids

    assets = fictional_asset_ids(Path(__file__).resolve().parents[2])
    assert {"A-03", "B-06", "GS-A", "C-04", "FL-A-03", "COMP-STATION"} <= assets
    assert not any(a.startswith("nm_ocd") for a in assets)


def test_card_json_round_trips():
    coverage = WellCoverage(
        source_asset_id="w",
        scenes_in_footprint=0,
        clear_scenes_in_footprint=0,
        scenes_without_footprint_in_bounds=0,
        plumes_within_radius=0,
        first_clear_scene=None,
        last_clear_scene=None,
        status=CoverageStatus.NOT_IMAGED,
    )
    card = build_card(coverage, [], {}, None, 250.0)
    assert (
        json.loads(card.model_dump_json())["headline"]
        == "No plume origin within 250 m in this batch"
    )
