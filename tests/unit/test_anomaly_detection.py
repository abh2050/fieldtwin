"""Label audit, splits, features, detectors, alarm rules, and metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from packages.anomaly_detection.detectors import make_detector, training_rows
from packages.anomaly_detection.evaluation import (
    UNSCORED,
    AlarmRule,
    AlarmState,
    bootstrap_intervals,
    by_class,
    calibrate_threshold,
    episode_starts,
    score_windows,
    select_preferred,
    summarize,
)
from packages.anomaly_detection.features import FeatureSpec, build_features, window_stats
from packages.anomaly_detection.labels import Evaluability, audit_labels
from packages.anomaly_detection.splits import (
    SplitLeakage,
    WellFold,
    assert_no_group_overlap,
    build_well_folds,
    credible_classes,
)

RULE = AlarmRule(persistence_windows=3, suppression_s=600, stride_s=60)
NAN = float("nan")
METHODS = [
    "static_threshold",
    "rolling_deviation",
    "logistic_regression",
    "isolation_forest",
    "hist_gradient_boosting",
]


def audit(labels, filed=9, origin="REAL"):
    return audit_labels(
        np.array(labels, dtype=float),
        instance_id="x",
        well_id="W",
        origin=origin,
        filed_class=filed,
        class_name="C",
    )


def test_event_class_file_without_event_rows_is_ambiguous_and_on_neither_side():
    result = audit([NAN, NAN, 0, 0, 0])
    assert result.evaluability == Evaluability.AMBIGUOUS_OR_INCONSISTENT
    assert not result.eligible_event_positive
    assert not result.eligible_sample_level
    assert not result.eligible_normal_exposure  # It isn't quietly counted as normal.


def test_only_transient_labels_still_count_as_an_event():
    result = audit([NAN, 0, 109, 109])
    assert result.evaluability == Evaluability.PARTIALLY_LABELED
    assert result.eligible_event_positive and result.has_pre_event_normal


def test_complete_labels_are_fully_labeled():
    result = audit([0, 0, 9, 109], origin="SIMULATED")
    assert result.evaluability == Evaluability.FULLY_LABELED


def test_labels_of_another_class_are_inconsistent():
    result = audit([0, 3, 9])
    assert (
        result.evaluability == Evaluability.AMBIGUOUS_OR_INCONSISTENT
        and result.other_class_rows == 1
    )


def test_normal_file_is_never_an_event_positive():
    result = audit([NAN, 0, 0], filed=0)
    assert result.evaluability == Evaluability.PARTIALLY_LABELED
    assert not result.eligible_event_positive and result.eligible_normal_exposure


def test_null_position_is_recorded():
    assert audit([NAN, NAN, 0, 9]).null_is_leading_only
    assert not audit([0, NAN, 9]).null_is_leading_only


def _instances():
    rows = []
    for well in range(30):
        for label in (0, 1 + well % 4):
            for i in range(2):
                rows.append(
                    {
                        "source_instance_id": f"{well}-{label}-{i}",
                        "source_well_id": f"W{well}",
                        "filed_class": label,
                    }
                )
    return pd.DataFrame(rows)


def test_folds_never_share_a_well_and_each_well_is_tested_once():
    holdout, folds = build_well_folds(
        _instances(), holdout_folds=5, development_folds=4, validation_folds=4, seed=1
    )
    for fold in (holdout, *folds):
        assert_no_group_overlap(fold)
    tested = [w for f in folds for w in f.test_wells]
    assert len(tested) == len(set(tested))
    assert not set(tested) & set(holdout.test_wells)
    assert set(tested) | set(holdout.test_wells) == {f"W{i}" for i in range(30)}
    # Development never trains or calibrates on the holdout.
    for fold in folds:
        assert not (set(fold.train_wells) | set(fold.validation_wells)) & set(holdout.test_wells)


def test_splits_are_deterministic():
    assert build_well_folds(
        _instances(), holdout_folds=5, development_folds=4, validation_folds=4, seed=1
    ) == build_well_folds(
        _instances(), holdout_folds=5, development_folds=4, validation_folds=4, seed=1
    )


def test_a_shared_well_is_refused():
    with pytest.raises(SplitLeakage):
        assert_no_group_overlap(WellFold("bad", ("A",), ("B",), ("A",)))


def test_thin_classes_are_marked_unsupported():
    frame = pd.DataFrame(
        {
            "filed_class": [1, 1, 2, 2, 2, 2, 2, 2],
            "source_well_id": ["A", "A", "A", "B", "C", "A", "B", "C"],
        }
    )
    table = credible_classes(frame, min_events=5, min_clusters=3).set_index("filed_class")
    assert not table.loc[1, "supports_evaluation"] and table.loc[2, "supports_evaluation"]


SPEC = FeatureSpec(("a", "b"), window_samples=5, stride_s=2, sample_s=1)


def test_stats_match_direct_calculation_and_missing_is_not_zero():
    window = np.array([[[1.0, np.nan], [2.0, np.nan], [3.0, 7.0], [4.0, 7.0], [5.0, 7.0]]])
    a_mean, a_std, a_slope, a_missing, b_mean, b_std, b_slope, b_missing = window_stats(
        window, 1.0
    )[0]
    assert (
        a_mean == 3
        and a_std == pytest.approx(np.std([1, 2, 3, 4, 5]))
        and a_slope == pytest.approx(1.0)
        and a_missing == 0
    )
    assert (
        b_mean == 7
        and b_std == 0
        and b_slope == pytest.approx(0.0)
        and b_missing == pytest.approx(0.4)
    )
    empty = window_stats(np.full((1, 5, 1), np.nan), 1.0)[0]
    assert np.isnan(empty[:3]).all() and empty[3] == 1.0


def test_features_are_causal():
    rng = np.random.default_rng(0)
    values = rng.normal(size=(40, 2))
    times = np.arange(40)
    before, ends = build_features(values, times, SPEC)
    changed = values.copy()
    changed[30:] += 1000.0
    after, _ = build_features(changed, times, SPEC)
    unaffected = ends < 30
    assert np.array_equal(before[unaffected], after[unaffected])
    assert not np.array_equal(before[~unaffected], after[~unaffected])


def test_windows_anchor_to_absolute_time_so_overlaps_align():
    _, first = build_features(np.zeros((30, 2)), np.arange(100, 130), SPEC)
    _, second = build_features(np.zeros((30, 2)), np.arange(103, 133), SPEC)
    assert set((np.arange(100, 130)[first]).tolist()) & set((np.arange(103, 133)[second]).tolist())
    assert (np.arange(100, 130)[first] % 2 == 0).all()


def _toy(seed=3, n=400, names=("s0", "s1", "s2")):
    rng = np.random.default_rng(seed)
    spec = FeatureSpec(tuple(names), 5, 1, 1)
    values = rng.normal(size=(n, len(names)))
    values[n // 2 :, 0] += 8.0
    features, ends = build_features(values, np.arange(n), spec)
    y = (ends >= n // 2).astype(int)
    return features, y, spec


@pytest.mark.parametrize("method", METHODS)
def test_each_method_separates_an_obvious_shift_with_training_data_only(method):
    features, y, spec = _toy()
    detector = make_detector(method, spec.names, seed=1, baseline_windows=20, gap_windows=5)
    seq = np.zeros(len(y), dtype=int)
    detector.fit(features, y, seq)
    scores = detector.score(features, seq)
    assert scores.shape == y.shape
    if (
        method != "rolling_deviation"
    ):  # A rolling baseline adapts to a level, so it marks the change.
        assert np.nanmean(scores[y == 1]) > np.nanmean(scores[y == 0])
    else:
        assert np.nanmax(scores[(y == 1)][:10]) > np.nanquantile(scores[y == 0], 0.99)


@pytest.mark.parametrize("method", METHODS)
def test_fitted_scores_ignore_data_outside_the_training_rows(method):
    features, y, spec = _toy()
    half = len(y) // 2
    train = np.r_[0 : half // 2, half : half + half // 2]
    other = features.copy()
    held = np.setdiff1d(np.arange(len(y)), train)
    other[held] = other[held] * 100 + 5
    seq = np.zeros(len(train), dtype=int)
    one = make_detector(method, spec.names, seed=1, baseline_windows=20, gap_windows=5).fit(
        features[train], y[train], seq
    )
    two = make_detector(method, spec.names, seed=1, baseline_windows=20, gap_windows=5).fit(
        other[train], y[train], seq
    )
    probe = features[:50]
    assert np.array_equal(
        one.score(probe, np.zeros(50, dtype=int)),
        two.score(probe, np.zeros(50, dtype=int)),
        equal_nan=True,
    )


def test_missing_sensor_keeps_gradient_boosting_and_imputers_working():
    features, y, spec = _toy()
    features[:, 4:8] = np.nan  # A sensor absent throughout.
    for method in (
        "logistic_regression",
        "isolation_forest",
        "hist_gradient_boosting",
        "static_threshold",
    ):
        detector = make_detector(method, spec.names, seed=1, baseline_windows=20, gap_windows=5)
        seq = np.zeros(len(y), dtype=int)
        scores = detector.fit(features, y, seq).score(features, seq)
        assert np.isfinite(scores).all(), method


def test_rolling_scores_are_causal():
    features, y, spec = _toy()
    detector = make_detector(
        "rolling_deviation", spec.names, seed=1, baseline_windows=20, gap_windows=5
    )
    seq = np.zeros(len(y), dtype=int)
    detector.fit(features, y, seq)
    full = detector.score(features, seq)
    cut = detector.score(features[:100], seq[:100])
    assert np.allclose(full[:100], cut, equal_nan=True)


def test_training_rows_never_include_unscored_and_are_capped():
    y = np.array([UNSCORED] * 50 + [0] * 100 + [1] * 5)
    rows = training_rows(y, cap_per_class=10, seed=0)
    assert (y[rows] != UNSCORED).all()
    assert (y[rows] == 0).sum() == 10 and (y[rows] == 1).sum() == 5


@given(
    scores=st.lists(
        st.one_of(st.floats(0, 1, allow_nan=False), st.just(float("nan"))), max_size=120
    ),
    threshold=st.floats(0.05, 0.95),
    persistence=st.integers(1, 4),
    suppression=st.integers(1, 12),
)
@settings(max_examples=200, deadline=None, derandomize=True)
def test_batch_and_streaming_alarms_agree(scores, threshold, persistence, suppression):
    rule = AlarmRule(persistence, suppression * 60, 60)
    array, times = np.array(scores, dtype=float), np.arange(len(scores)) * 60
    state = AlarmState(rule)
    streamed = [i for i, s in enumerate(scores) if state.step(s, threshold, int(times[i]))]
    assert episode_starts(array, times, threshold, rule)[0].tolist() == streamed


def test_persistence_and_merging_of_repeated_alerts():
    times = np.arange(20) * 60
    scores = np.array([0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1] + [0] * 8, dtype=float)
    starts, _ = episode_starts(scores, times, 0.5, RULE)
    assert starts.tolist() == [
        6
    ]  # Two windows above isn't enough, and later alerts merge into one.
    late = np.array([1, 1, 1] + [0] * 12 + [1, 1, 1, 0, 0], dtype=float)
    assert episode_starts(late, times, 0.5, RULE)[0].tolist() == [2, 17]


def _table(y, seq="s", cluster="w", start=0):
    return pd.DataFrame(
        {"seq": seq, "cluster": cluster, "t": start + np.arange(len(y)) * 60, "y": y}
    )


def test_detection_requires_an_episode_starting_inside_the_event():
    y = np.array([0] * 10 + [4] * 10)
    inside = np.array([0] * 12 + [1] * 8, dtype=float)
    result = score_windows(_table(y), inside, 0.5, RULE)
    assert result.events["detected"].tolist() == [True] and result.events["delay_s"].iloc[0] == 240
    assert summarize(result)["false_alarms"] == 0


def test_alarm_already_running_at_onset_is_a_false_alarm_and_not_a_detection():
    y = np.array([0] * 10 + [4] * 10)
    early = np.array([0] * 5 + [1] * 15, dtype=float)
    result = score_windows(_table(y), early, 0.5, RULE)
    summary = summarize(result)
    assert not result.events["detected"].iloc[0]
    assert result.events["active_at_onset"].iloc[0]
    assert summary["false_alarms"] == 1 and summary["active_at_onset_not_counted"] == 1


def test_unlabeled_rows_count_as_nothing():
    y = np.array([UNSCORED] * 10 + [0] * 10)
    scores = np.array([1] * 5 + [0] * 15, dtype=float)
    summary = summarize(score_windows(_table(y), scores, 0.5, RULE))
    assert summary["false_alarms"] == 0 and summary["fp"] == 0 and summary["events"] == 0
    assert summary["normal_hours"] == pytest.approx(10 * 60 / 3600)


def test_overlapping_instances_count_each_well_and_time_once():
    y = np.zeros(20, dtype=int)
    scores = np.array([0] * 5 + [1] * 5 + [0] * 10, dtype=float)
    table = pd.concat([_table(y, "a"), _table(y, "b")], ignore_index=True)
    summary = summarize(score_windows(table, np.r_[scores, scores], 0.5, RULE))
    assert summary["normal_hours"] == pytest.approx(20 * 60 / 3600)
    assert summary["false_alarms"] == 1 and summary["fp"] == 5


def test_missing_scores_never_fire():
    y = np.zeros(10, dtype=int)
    assert summarize(score_windows(_table(y), np.full(10, np.nan), 0.5, RULE))["fp"] == 0


def _clusters(count, detected_each=(True, False)):
    tables = []
    scores = []
    for i in range(count):
        y = np.array([0] * 10 + [4] * 10)
        hit = detected_each[i % len(detected_each)]
        tables.append(_table(y, f"s{i}", f"w{i}"))
        scores.append(np.array([0] * 12 + ([1] * 8 if hit else [0] * 8), dtype=float))
    return pd.concat(tables, ignore_index=True), np.concatenate(scores)


def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    table, scores = _clusters(10)
    counts = score_windows(table, scores, 0.5, RULE)
    one = bootstrap_intervals(counts, resamples=300, confidence=0.95, seed=4)
    assert one == bootstrap_intervals(counts, resamples=300, confidence=0.95, seed=4)
    low, high = one["event_recall"]
    assert low <= 0.5 <= high and low < high


def test_recall_is_withheld_for_unsupported_groups():
    table, scores = _clusters(2)
    counts = score_windows(table, scores, 0.5, RULE)
    support = {"min_events": 5, "min_clusters": 3, "min_clusters_for_interval": 5}
    row = by_class(counts, support, resamples=50, confidence=0.95, seed=1)[0]
    assert row["event_recall"] is None and "withheld_reason" in row
    table, scores = _clusters(6)
    row = by_class(
        score_windows(table, scores, 0.5, RULE), support, resamples=50, confidence=0.95, seed=1
    )[0]
    assert row["event_recall"] == pytest.approx(0.5) and "event_recall_interval" in row


def test_calibration_uses_the_lowest_threshold_within_budget():
    y = np.zeros(600, dtype=int)
    scores = np.random.default_rng(0).random(600)
    result = calibrate_threshold(_table(y), scores, RULE, budget=0.2, grid_points=40)
    assert result["budget_met"]
    assert (
        summarize(score_windows(_table(y), scores, result["threshold"], RULE))[
            "false_alarms_per_hour"
        ]
        <= 0.2
    )


def _row(method, skill, alarms, low, high):
    return {
        "method": method,
        "event_skill": skill,
        "false_alarms_per_hour": alarms,
        "interval": {"event_skill": [low, high]},
    }


def test_selection_prefers_the_simplest_tied_method():
    order = ["simple", "medium", "complex"]
    rows = [
        _row("simple", 0.6, 0.01, 0.4, 0.8),
        _row("medium", 0.5, 0.01, 0.3, 0.6),
        _row("complex", 0.7, 0.04, 0.5, 0.9),
    ]
    assert select_preferred(rows, order=order, budget=0.05)["preferred"] == "simple"


def test_selection_excludes_methods_over_budget():
    order = ["simple", "complex"]
    rows = [_row("simple", 0.9, 1.0, 0.8, 1.0), _row("complex", 0.5, 0.01, 0.4, 0.6)]
    assert select_preferred(rows, order=order, budget=0.05)["preferred"] == "complex"
    assert (
        select_preferred([_row("simple", 0.9, 1.0, 0.8, 1.0)], order=order, budget=0.05)[
            "preferred"
        ]
        is None
    )


def test_calibration_doesnt_choose_an_alarm_that_never_turns_off():
    # Brief spikes above a low flat level. A threshold under the flat level gives one endless episode,
    # so it passes on false alarms per hour alone.
    scores = np.full(3000, 0.2)
    for offset in range(3):
        scores[offset::100] = 0.9
    y = np.zeros(3000, dtype=int)
    table = _table(y)
    flat = summarize(score_windows(table, scores, 0.1, RULE))
    assert (
        flat["false_alarms_per_hour"] < 0.05 and flat["time_in_alarm"] > 0.99
    )  # Persistence leaves 2 windows out.
    result = calibrate_threshold(
        table, scores, RULE, budget=0.05, grid_points=40, max_time_in_alarm=0.05
    )
    assert result["threshold"] > 0.2


def test_time_in_alarm_is_measured_on_normal_windows():
    y = np.array([0] * 100 + [4] * 100)
    scores = np.zeros(200)
    scores[10:13] = 1.0
    summary = summarize(score_windows(_table(y), scores, 0.5, RULE))
    assert 0.0 < summary["time_in_alarm"] < 0.2


def test_chance_level_rises_with_event_duration():
    y = np.array([0] * 600 + [4] * 3000)
    scores = np.zeros(3600)
    for start in (100, 300, 500):
        scores[start : start + 3] = 1.0
    summary = summarize(score_windows(_table(y), scores, 0.5, RULE))
    rate = summary["false_alarms_per_hour"]
    assert summary["chance_event_recall"] == pytest.approx(1.0 - np.exp(-rate * (2999 / 60)))
    assert summary["event_skill"] == pytest.approx(
        summary["event_recall"] - summary["chance_event_recall"]
    )


def test_classifier_scores_keep_resolution_when_normal_is_nearly_impossible():
    features, y, spec = _toy()
    features[y == 1, 0] += 1000.0  # Far beyond anything normal, so P(normal) underflows.
    seq = np.zeros(len(y), dtype=int)
    detector = make_detector(
        "logistic_regression", spec.names, seed=1, baseline_windows=20, gap_windows=5
    ).fit(features, y, seq)
    scores = detector.score(features, seq)
    assert np.isfinite(scores).all()
    shifted = scores[y == 1]
    assert len(np.unique(shifted)) > len(shifted) // 2  # Not all tied, as 1 - P would be.


def test_an_alarm_after_the_event_returns_to_normal_is_a_false_alarm_not_a_detection():
    y = np.array([0] * 10 + [4] * 10 + [0] * 20)
    late = np.zeros(40)
    late[25:29] = 1.0  # Starts after the last event-labeled row.
    result = score_windows(_table(y), late, 0.5, RULE)
    summary = summarize(result)
    assert not result.events["detected"].iloc[0]
    assert summary["false_alarms"] == 1
    assert result.events["duration_h"].iloc[0] == pytest.approx(9 * 60 / 3600)


def test_calibration_can_choose_a_threshold_below_the_median():
    # Two high windows, then a zero, repeating. Nothing persists for 3 windows, so any threshold above
    # zero is within budget, including ones well below the median.
    rng = np.random.default_rng(1)
    scores = 0.9 + 0.1 * rng.random(3000)
    scores[2::3] = 0.0
    y = np.zeros(3000, dtype=int)
    result = calibrate_threshold(
        _table(y), scores, RULE, budget=0.05, grid_points=60, max_time_in_alarm=0.05
    )
    assert 0.0 < result["threshold"] < float(np.median(scores))


def test_classifier_scores_stay_finite_when_normal_has_probability_zero():
    features, y, spec = _toy()
    features[y == 1, 0] += 1e6  # Far enough that predict_proba gives exactly 0 for normal.
    seq = np.zeros(len(y), dtype=int)
    for method in ("logistic_regression", "hist_gradient_boosting"):
        detector = make_detector(
            method, spec.names, seed=1, baseline_windows=20, gap_windows=5
        ).fit(features, y, seq)
        assert np.isfinite(detector.score(features, seq)).all(), method


def test_logistic_regression_refuses_to_return_an_unconverged_fit():
    from packages.anomaly_detection.detectors import FitDidNotConverge, Logistic

    features, y, _ = _toy()
    with pytest.raises(FitDidNotConverge):
        Logistic(seed=1, max_iter=1).fit(features, y, np.zeros(len(y), dtype=int))
    fitted = Logistic(seed=1).fit(features, y, np.zeros(len(y), dtype=int))
    assert (
        fitted.fit_report["converged"]
        and fitted.fit_report["iterations"] < fitted.fit_report["max_iter"]
    )
