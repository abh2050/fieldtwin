"""Alarm logic and metrics, implementing config/experiments/gate5_evaluation.yaml.

Sample-level and event-level results are separate. Uncertainty comes from resampling whole clusters
(wells or cases), because windows and instances within one cluster aren't independent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

UNSCORED = -1


@dataclass(frozen=True)
class AlarmRule:
    persistence_windows: int
    suppression_s: int
    stride_s: int


class AlarmState:
    """The alarm rule, one window at a time. `episode_starts` must give the same answer in batch."""

    def __init__(self, rule: AlarmRule):
        self.rule = rule
        self.run = 0
        self.active = False
        self.last_above = 0
        self.first_above_of_run = 0

    def step(self, score: float, threshold: float, time_s: int) -> bool:
        """Return True when this window starts a new episode. A missing score counts as below."""
        if score == score and score >= threshold:
            if self.run == 0:
                self.first_above_of_run = time_s
            self.run += 1
            if self.active:
                self.last_above = time_s
                return False
            if self.run >= self.rule.persistence_windows:
                self.active, self.last_above = True, time_s
                return True
            return False
        self.run = 0
        if self.active and time_s - self.last_above >= self.rule.suppression_s:
            self.active = False
        return False


def episode_starts(
    scores: np.ndarray, times: np.ndarray, threshold: float, rule: AlarmRule
) -> tuple[np.ndarray, np.ndarray]:
    """Indices that start an episode, and indices where an episode is still running."""
    above = np.flatnonzero(np.nan_to_num(scores, nan=-np.inf) >= threshold)
    starts: list[int] = []
    spans: list[tuple[int, float]] = []
    run, active, last, previous = 0, False, 0, -2
    for index in above.tolist():
        if active and index - 1 > previous and times[index - 1] - last >= rule.suppression_s:
            active = False
            spans[-1] = (spans[-1][0], last + rule.suppression_s)
        run = run + 1 if index == previous + 1 else 1
        previous = index
        if active:
            last = times[index]
        elif run >= rule.persistence_windows:
            active, last = True, times[index]
            starts.append(index)
            spans.append((index, -1.0))
    if active:
        spans[-1] = (spans[-1][0], last + rule.suppression_s)
    running = np.zeros(len(scores), dtype=bool)
    for start, until in spans:
        running[start:] |= times[start:] <= until
    return np.array(starts, dtype=np.int64), running


@dataclass(frozen=True)
class ClusterCounts:
    """Per-cluster results, so resampling can rebuild any metric."""

    table: pd.DataFrame
    events: pd.DataFrame


def score_windows(
    table: pd.DataFrame, scores: np.ndarray, threshold: float, rule: AlarmRule
) -> ClusterCounts:
    """`table` holds seq, cluster, t, y. y is the class, 0 for normal, or UNSCORED."""
    rows = table.reset_index(drop=True)
    y = rows["y"].to_numpy()
    fired = np.nan_to_num(scores, nan=-np.inf) >= threshold
    # Overlapping 3W instances hold identical rows, so each well and time counts once.
    first = ~rows.duplicated(["cluster", "t"]).to_numpy()
    scored = first & (y != UNSCORED)
    frame = pd.DataFrame(
        {
            "cluster": rows["cluster"],
            "tp": scored & (y > 0) & fired,
            "fn": scored & (y > 0) & ~fired,
            "fp": scored & (y == 0) & fired,
            "tn": scored & (y == 0) & ~fired,
        }
    )
    per_cluster = frame.groupby("cluster", sort=True).sum()
    per_cluster["normal_hours"] = (per_cluster["fp"] + per_cluster["tn"]) * rule.stride_s / 3600.0
    per_cluster["false_alarms"] = 0
    per_cluster["alarm_normal_windows"] = 0

    seen: set[tuple[str, int]] = set()
    events = []
    times = rows["t"].to_numpy()
    positions = rows.groupby("seq", sort=False).indices
    for seq, index in positions.items():
        index = np.sort(index)
        cluster = rows["cluster"].iloc[index[0]]
        starts, running = episode_starts(scores[index], times[index], threshold, rule)
        labels = y[index]
        per_cluster.loc[cluster, "alarm_normal_windows"] += int(
            (running & scored[index] & (labels == 0)).sum()
        )
        for start in starts:
            key = (cluster, int(times[index][start]))
            if labels[start] == 0 and key not in seen:
                seen.add(key)
                per_cluster.loc[cluster, "false_alarms"] += 1
        positive = np.flatnonzero(labels > 0)
        if positive.size:
            onset = int(positive[0])
            scored_end = int(np.flatnonzero(labels != UNSCORED)[-1])
            inside = starts[(starts >= onset) & (starts <= scored_end)]
            events.append(
                {
                    "seq": seq,
                    "cluster": cluster,
                    "event_class": int(labels[onset]),
                    "detected": bool(inside.size),
                    "active_at_onset": bool(running[onset]) and bool((starts < onset).any()),
                    "delay_s": float(times[index][inside[0]] - times[index][onset])
                    if inside.size
                    else np.nan,
                    "duration_h": float(times[index][scored_end] - times[index][onset]) / 3600.0,
                }
            )
    columns = [
        "seq",
        "cluster",
        "event_class",
        "detected",
        "active_at_onset",
        "delay_s",
        "duration_h",
    ]
    return ClusterCounts(per_cluster, pd.DataFrame(events, columns=columns))


def _ratios(
    tp: float,
    fp: float,
    fn: float,
    tn: float,
    false_alarms: float,
    hours: float,
    events: float,
    detected: float,
    alarm_windows: float = 0.0,
    chance_sum: float = 0.0,
) -> dict[str, float]:
    def safe(a: float, b: float) -> float:
        return a / b if b > 0 else float("nan")

    precision, recall = safe(tp, tp + fp), safe(tp, tp + fn)
    event_recall, chance = safe(detected, events), safe(chance_sum, events)
    return {
        "precision": precision,
        "recall": recall,
        "f1": safe(2 * precision * recall, precision + recall)
        if precision == precision and recall == recall
        else float("nan"),
        "false_positive_rate": safe(fp, fp + tn),
        "false_alarms_per_hour": safe(false_alarms, hours),
        "time_in_alarm": safe(alarm_windows, fp + tn),
        "event_recall": event_recall,
        "chance_event_recall": chance,
        "event_skill": event_recall - chance,
    }


def _chance_sum(durations_h: np.ndarray, rate_per_hour: float) -> float:
    """Expected detections from alarms unrelated to any event. See `chance_level` in the configuration."""
    if rate_per_hour != rate_per_hour:
        return 0.0
    return float((1.0 - np.exp(-rate_per_hour * durations_h)).sum())


def summarize(counts: ClusterCounts) -> dict:
    """Point estimates and raw counts."""
    table, events = counts.table, counts.events
    totals = table[
        ["tp", "fp", "fn", "tn", "false_alarms", "normal_hours", "alarm_normal_windows"]
    ].sum()
    rate = (
        totals["false_alarms"] / totals["normal_hours"]
        if totals["normal_hours"] > 0
        else float("nan")
    )
    result = _ratios(
        totals["tp"], totals["fp"], totals["fn"], totals["tn"], totals["false_alarms"], totals["normal_hours"],
        len(events), float(events["detected"].sum()) if len(events) else 0.0,
        totals["alarm_normal_windows"], _chance_sum(events["duration_h"].to_numpy(dtype=float), rate),
    )  # fmt: skip
    result.update(
        {
            "tp": int(totals["tp"]), "fp": int(totals["fp"]), "fn": int(totals["fn"]), "tn": int(totals["tn"]),
            "false_alarms": int(totals["false_alarms"]),
            "normal_hours": float(totals["normal_hours"]),
            "events": len(events),
            "events_detected": int(events["detected"].sum()) if len(events) else 0,
            "active_at_onset_not_counted": int(events["active_at_onset"].sum()) if len(events) else 0,
            "clusters": int(table.shape[0]),
            "event_clusters": int(events["cluster"].nunique()) if len(events) else 0,
        }
    )  # fmt: skip
    return result


def bootstrap_intervals(
    counts: ClusterCounts, *, resamples: int, confidence: float, seed: int
) -> dict[str, list[float]]:
    """Percentile intervals from resampling clusters with replacement."""
    table, events = counts.table, counts.events
    clusters = table.index.to_numpy()
    if clusters.size == 0:
        return {}
    per_event = (
        events.groupby("cluster")["detected"].agg(["size", "sum"]).reindex(clusters, fill_value=0)
    )
    values = table[
        ["tp", "fp", "fn", "tn", "false_alarms", "normal_hours", "alarm_normal_windows"]
    ].to_numpy(dtype=float)
    event_values = per_event.to_numpy(dtype=float)
    position = {cluster: i for i, cluster in enumerate(clusters)}
    event_cluster = events["cluster"].map(position).to_numpy(dtype=int)
    durations = events["duration_h"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, clusters.size, size=(resamples, clusters.size))
    collected: dict[str, list[float]] = {}
    for draw in draws:
        tp, fp, fn, tn, alarms, hours, alarm_windows = values[draw].sum(axis=0)
        size, detected = event_values[draw].sum(axis=0)
        weights = np.bincount(draw, minlength=clusters.size)[event_cluster]
        rate = alarms / hours if hours > 0 else float("nan")
        chance = float((weights * (1.0 - np.exp(-rate * durations))).sum()) if rate == rate else 0.0
        for key, value in _ratios(
            tp, fp, fn, tn, alarms, hours, size, detected, alarm_windows, chance
        ).items():
            collected.setdefault(key, []).append(value)
    tail = (1.0 - confidence) / 2.0
    output = {}
    for key, samples in collected.items():
        array = np.array(samples, dtype=float)
        array = array[~np.isnan(array)]
        if array.size:
            output[key] = [float(np.quantile(array, tail)), float(np.quantile(array, 1.0 - tail))]
    return output


def average_precision(table: pd.DataFrame, scores: np.ndarray) -> float | None:
    rows = table.reset_index(drop=True)
    keep = (~rows.duplicated(["cluster", "t"])).to_numpy() & (rows["y"].to_numpy() != UNSCORED)
    y = rows["y"].to_numpy()[keep] > 0
    if y.sum() == 0 or (~y).sum() == 0:
        return None
    filled = np.nan_to_num(scores[keep], nan=-np.inf, posinf=np.finfo(float).max)
    floor = filled[np.isfinite(filled)].min() - 1.0 if np.isfinite(filled).any() else 0.0
    return float(average_precision_score(y, np.where(np.isfinite(filled), filled, floor)))


def calibrate_threshold(
    table: pd.DataFrame,
    scores: np.ndarray,
    rule: AlarmRule,
    *,
    budget: float,
    grid_points: int,
    max_time_in_alarm: float = 0.05,
) -> dict:
    """Walk down from a threshold nothing reaches, and stop at the first violation.

    Taking the lowest passing threshold isn't safe. An alarm that never turns off is one episode, so very
    low thresholds can look cheap in false alarms per hour while being useless.
    """
    finite = scores[np.isfinite(scores)]
    if finite.size == 0:
        raise ValueError("no finite validation scores")
    tail = 1.0 - np.logspace(-5, np.log10(0.5), grid_points)
    candidates = np.unique(np.quantile(finite, tail))[::-1]
    chosen = float(finite.max()) + max(abs(float(finite.max())) * 1e-6, 1e-9)
    achieved = summarize(score_windows(table, scores, chosen, rule))
    stopped_by = "reached the end of the grid"
    for threshold in candidates:
        result = summarize(score_windows(table, scores, float(threshold), rule))
        rate, in_alarm = result["false_alarms_per_hour"], result["time_in_alarm"]
        if rate == rate and rate > budget:
            stopped_by = "false-alarm budget"
            break
        if in_alarm == in_alarm and in_alarm > max_time_in_alarm:
            stopped_by = "time-in-alarm limit"
            break
        chosen, achieved = float(threshold), result
    return {
        "threshold": chosen,
        "validation_false_alarms_per_hour": achieved["false_alarms_per_hour"],
        "validation_time_in_alarm": achieved["time_in_alarm"],
        "validation_event_recall": achieved["event_recall"],
        "stopped_by": stopped_by,
        "budget_met": True,
    }


def supported(summary: dict, support: dict) -> bool:
    return (
        summary["events"] >= support["min_events"]
        and summary["event_clusters"] >= support["min_clusters"]
    )


def by_class(
    counts: ClusterCounts, support: dict, *, resamples: int, confidence: float, seed: int
) -> list[dict]:
    """Event recall per class, with recall withheld where support is too thin."""
    rows = []
    for label, group in counts.events.groupby("event_class"):
        count, clusters = len(group), group["cluster"].nunique()
        row = {
            "event_class": int(label),
            "events": count,
            "clusters": clusters,
            "detected": int(group["detected"].sum()),
        }
        if count >= support["min_events"] and clusters >= support["min_clusters"]:
            row["event_recall"] = float(group["detected"].mean())
            if clusters >= support["min_clusters_for_interval"]:
                rng = np.random.default_rng(seed + int(label))
                per = (
                    group.groupby("cluster")["detected"].agg(["size", "sum"]).to_numpy(dtype=float)
                )
                draws = rng.integers(0, len(per), size=(resamples, len(per)))
                sampled = per[draws].sum(axis=1)
                ratio = sampled[:, 1] / sampled[:, 0]
                tail = (1.0 - confidence) / 2.0
                row["event_recall_interval"] = [
                    float(np.quantile(ratio, tail)),
                    float(np.quantile(ratio, 1 - tail)),
                ]
        else:
            row["event_recall"] = None
            row["withheld_reason"] = (
                f"Fewer than {support['min_events']} events or {support['min_clusters']} clusters."
            )
        rows.append(row)
    return rows


def select_preferred(rows: list[dict], *, order: list[str], budget: float) -> dict:
    """The declared rule: within budget, best skill, then the simplest method statistically tied."""
    eligible = [
        r
        for r in rows
        if r["false_alarms_per_hour"] == r["false_alarms_per_hour"]
        and r["false_alarms_per_hour"] <= budget
    ]
    if not eligible:
        return {"preferred": None, "reason": "No method met the false-alarm budget.", "tied": []}
    best = max(eligible, key=lambda r: r["event_skill"])
    tied = [
        r["method"]
        for r in eligible
        if r["interval"].get("event_skill", [0, 0])[0]
        <= best["event_skill"]
        <= r["interval"].get("event_skill", [0, 0])[1]
    ]
    if best["method"] not in tied:
        tied.append(best["method"])
    preferred = min(tied, key=order.index)
    return {
        "preferred": preferred,
        "reason": f"{best['method']} had the best event skill within budget ({best['event_skill']:.3f}). {len(tied)} method(s) have skill intervals including it, and {preferred} is the simplest of them.",
        "tied": tied,
    }
