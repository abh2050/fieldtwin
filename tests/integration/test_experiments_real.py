"""Gate 5 checks that need acquired 3W data. Run with `pytest -m acquired -o addopts=''`."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.acquired


@pytest.fixture(scope="module")
def audits():
    from pipelines.experiments.three_w_audit import run_audit

    return run_audit()


def test_every_instance_is_audited(audits):
    assert len(audits) == 498
    assert audits.groupby("origin").size().to_dict() == {
        "HAND_DRAWN": 20,
        "REAL": 342,
        "SIMULATED": 136,
    }


def test_the_43_class_9_instances_are_ambiguous_and_excluded(audits):
    ambiguous = audits[audits["evaluability"] == "AMBIGUOUS_OR_INCONSISTENT"]
    assert len(ambiguous) == 43
    assert set(ambiguous["filed_class"]) == {9} and set(ambiguous["origin"]) == {"REAL"}
    assert not ambiguous["eligible_event_positive"].any()
    assert not ambiguous["eligible_normal_exposure"].any()


def test_source_labels_are_never_changed(audits):
    from pipelines.experiments.three_w_data import load_track

    track, meta, _ = load_track()
    ambiguous = meta["evaluability"] == "AMBIGUOUS_OR_INCONSISTENT"
    assert (track.table.loc[ambiguous, "y"] == -1).all()
    assert (meta.loc[ambiguous & (meta["raw_label"] >= 0), "source_y"] == 0).all()


def test_splits_keep_every_well_on_one_side(audits):
    from packages.anomaly_detection.splits import assert_no_group_overlap, build_well_folds

    real = audits[audits["origin"] == "REAL"]
    holdout, folds = build_well_folds(
        real, holdout_folds=5, development_folds=4, validation_folds=4, seed=50005
    )
    for fold in (holdout, *folds):
        assert_no_group_overlap(fold)
    tested = [w for f in folds for w in f.test_wells] + list(holdout.test_wells)
    assert sorted(tested) == sorted(real["source_well_id"].unique())


def test_derived_windows_hold_no_impossible_or_infinite_values():
    from pipelines.experiments.three_w_data import load_track

    track, _, _ = load_track()
    assert not np.isinf(track.features).any()
    assert np.nanmax(np.abs(track.features)) < 1e9


def test_windows_never_cross_instances_and_end_on_minute_boundaries():
    from pipelines.experiments.three_w_data import load_track

    track, _, _ = load_track()
    table = track.table
    assert (table["t"] % 60 == 0).all()
    assert table.groupby("seq")["t"].apply(lambda t: t.is_monotonic_increasing).all()


def test_overlapping_instances_hold_identical_rows_where_they_share_time():
    from pipelines.experiments.three_w_data import load_track

    track, _, _ = load_track()
    frame = pd.DataFrame(track.features[:, :8]).assign(
        well=track.table["well"].to_numpy(), t=track.table["t"].to_numpy()
    )
    shared = frame[frame.duplicated(["well", "t"], keep=False)]
    assert len(shared) > 0
    spread = shared.groupby(["well", "t"]).nunique(dropna=False).drop(columns=[]).max().max()
    assert spread == 1


def test_recorded_results_name_the_code_and_data_they_came_from():
    from pipelines.experiments.common import RESULTS

    for name in ("3w_development", "3w_holdout"):
        path = RESULTS / f"{name}.json"
        if path.exists():
            result = json.loads(path.read_text())
            assert len(result["git_sha"]) == 40 and len(result["dataset_sha256"]) == 64


def test_generated_instances_sharing_a_name_stay_separate(audits):
    from pipelines.experiments.three_w_data import load_track

    _, meta, _ = load_track()
    generated = audits[audits["origin"] != "REAL"]
    assert (
        generated["source_instance_id"].duplicated().any()
    )  # The source reuses names across classes.
    assert meta.loc[meta["origin"] != "REAL", "seq"].nunique() == len(generated)
    assert meta.groupby("seq")["filed_class"].nunique().max() == 1
