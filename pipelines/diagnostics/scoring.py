"""Score diagnoses exactly as the preregistration defines. Reads truth; never used by a diagnosis."""

from __future__ import annotations

from typing import Any

import numpy as np

NONE = "NONE"


def hypotheses(prereg: dict[str, Any]) -> list[str]:
    return [NONE, *prereg["hypotheses"]["candidate_pipes"]]


def climatology(prereg: dict[str, Any], regime: str = "in_regime") -> dict[str, float]:
    """B0: the generator's own class frequencies for a regime."""
    g = prereg["generator"]
    pipes = g["in_regime"]["restriction_pipes"]
    if regime != "in_regime" and "restriction_pipes" in g["held_out_regimes"].get(regime, {}):
        pipes = g["held_out_regimes"][regime]["restriction_pipes"]
    share = g["restriction_share"]
    return {
        h: (1 - share if h == NONE else (share / len(pipes) if h in pipes else 0.0))
        for h in hypotheses(prereg)
    }


def brier(probabilities: dict[str, float], truth: str, labels: list[str]) -> float:
    return float(
        sum((probabilities.get(h, 0.0) - (1.0 if h == truth else 0.0)) ** 2 for h in labels)
    )


def bootstrap(
    values: np.ndarray, statistic, seed: int, resamples: int = 2000
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(values)
    stats = [statistic(values[rng.integers(0, n, n)]) for _ in range(resamples)]
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def score(
    rows: list[dict[str, Any]], prereg: dict[str, Any], regime: str | None = None
) -> dict[str, Any]:
    """Rows hold per-case results: truth, diagnosis, after-measurement diagnosis, and comparators.

    With a held-out `regime`, Brier skill is also reported against that regime's own generator
    frequencies, alongside the fixed in-regime climatology that stays the acceptance comparator.
    """
    if not rows:
        return {
            "cases": 0,
            "primary_cases": 0,
            "no_restriction_cases": 0,
            "material_subset_cases": 0,
        }
    s = prereg["scoring"]
    seed = s["intervals"].split("seed ")[-1] if isinstance(s["intervals"], str) else 20261111
    seed = int(str(seed).strip()) if str(seed).strip().isdigit() else 20261111
    labels = hypotheses(prereg)
    primary = [r for r in rows if r["truth"]["faulted_pipe"] != NONE]
    nones = [r for r in rows if r["truth"]["faulted_pipe"] == NONE]
    material = [
        r
        for r in primary
        if r["truth"]["production_impact_sm3_per_s"]
        >= 0.01 * r["truth"]["no_restriction_field_flow_sm3_per_s"]
    ]

    def top1(rs, key="diagnosis"):
        return np.array(
            [r[key]["ranking"][0] == r["truth"]["faulted_pipe"] for r in rs], dtype=float
        )

    def top3(rs):
        return np.array(
            [r["truth"]["faulted_pipe"] in r["diagnosis"]["ranking"][:3] for r in rs], dtype=float
        )

    def rr(rs):
        return np.array(
            [1.0 / (r["diagnosis"]["ranking"].index(r["truth"]["faulted_pipe"]) + 1) for r in rs]
        )

    def impact_ok(r):
        t = r["truth"]["production_impact_sm3_per_s"]
        floor = 0.0005 * r["truth"]["no_restriction_field_flow_sm3_per_s"]
        return abs(r["diagnosis"]["impact"]["point"] - t) <= max(0.2 * abs(t), floor)

    def severity_ok(r):
        return abs(r["diagnosis"]["severity"]["point"] - r["truth"]["severity"]) <= 0.10

    out: dict[str, Any] = {
        "cases": len(rows),
        "primary_cases": len(primary),
        "no_restriction_cases": len(nones),
        "material_subset_cases": len(material),
    }
    if primary:
        t1 = top1(primary)
        out["top1"] = float(t1.mean())
        out["top1_interval"] = bootstrap(t1, np.mean, seed)
        out["top3"] = float(top3(primary).mean())
        out["mean_reciprocal_rank"] = float(rr(primary).mean())
        out["miss_rate"] = float(np.mean([r["diagnosis"]["ranking"][0] == NONE for r in primary]))
        correct = [r for r in primary if r["diagnosis"]["ranking"][0] == r["truth"]["faulted_pipe"]]
        out["severity_conditional_mae"] = (
            float(
                np.mean(
                    [
                        abs(r["diagnosis"]["severity"]["point"] - r["truth"]["severity"])
                        for r in correct
                    ]
                )
            )
            if correct
            else None
        )
        joint = np.array(
            [
                r["diagnosis"]["ranking"][0] == r["truth"]["faulted_pipe"]
                and severity_ok(r)
                and impact_ok(r)
                for r in primary
            ],
            dtype=float,
        )
        out["joint_success_rate"] = float(joint.mean())
        out["joint_success_interval"] = bootstrap(joint, np.mean, seed)
        out["impact_within_tolerance"] = float(np.mean([impact_ok(r) for r in primary]))
        big = [
            r
            for r in primary
            if r["truth"]["production_impact_sm3_per_s"]
            >= 0.001 * r["truth"]["no_restriction_field_flow_sm3_per_s"]
        ]
        out["impact_relative_error_cases"] = len(big)
        out["impact_median_relative_error"] = (
            float(
                np.median(
                    [
                        abs(
                            r["diagnosis"]["impact"]["point"]
                            - r["truth"]["production_impact_sm3_per_s"]
                        )
                        / r["truth"]["production_impact_sm3_per_s"]
                        for r in big
                    ]
                )
            )
            if big
            else None
        )

        def coverage(key, lo, hi):
            return float(
                np.mean(
                    [
                        r["diagnosis"][key][lo]
                        <= (
                            r["truth"]["severity"]
                            if key == "severity"
                            else r["truth"]["production_impact_sm3_per_s"]
                        )
                        <= r["diagnosis"][key][hi]
                        for r in primary
                    ]
                )
            )

        out["coverage_80"] = {
            "severity": coverage("severity", "p10", "p90"),
            "impact": coverage("impact", "p10", "p90"),
        }
        out["coverage_95"] = {
            "severity": coverage("severity", "p2_5", "p97_5"),
            "impact": coverage("impact", "p2_5", "p97_5"),
        }
        if "b1" in primary[0]:
            b1 = np.array(
                [r["b1"]["ranking"][0] == r["truth"]["faulted_pipe"] for r in primary], dtype=float
            )
            out["b1_top1"] = float(b1.mean())
            out["top1_minus_b1_interval"] = bootstrap(t1 - b1, np.mean, seed)
    if nones:
        out["specificity"] = float(np.mean([r["diagnosis"]["ranking"][0] == NONE for r in nones]))
    clim = climatology(prereg)
    model_brier = np.array(
        [brier(r["diagnosis"]["probabilities"], r["truth"]["faulted_pipe"], labels) for r in rows]
    )
    clim_brier = np.array([brier(clim, r["truth"]["faulted_pipe"], labels) for r in rows])
    uniform = {h: 1 / len(labels) for h in labels}
    uni_brier = np.array([brier(uniform, r["truth"]["faulted_pipe"], labels) for r in rows])
    out["brier_skill_score_vs_climatology"] = float(1 - model_brier.mean() / clim_brier.mean())
    out["brier_skill_score_vs_uniform"] = float(1 - model_brier.mean() / uni_brier.mean())
    if regime is not None:
        own = climatology(prereg, regime)
        own_brier = np.array([brier(own, r["truth"]["faulted_pipe"], labels) for r in rows])
        out["regime_climatology"] = own
        out["brier_skill_score_vs_regime_climatology"] = float(
            1 - model_brier.mean() / own_brier.mean()
        )
    # Pipe-level results only where support reaches the frozen minimum; the rest are INCONCLUSIVE.
    minimum = prereg["minimum_support"]["per_pipe"]["primary_cases"]
    per_pipe: dict[str, Any] = {}
    for pipe in prereg["hypotheses"]["candidate_pipes"]:
        mine = [r for r in primary if r["truth"]["faulted_pipe"] == pipe]
        if len(mine) < minimum:
            per_pipe[pipe] = {"primary_cases": len(mine), "status": "INCONCLUSIVE"}
            continue
        hits = [r for r in mine if r["diagnosis"]["ranking"][0] == pipe]
        per_pipe[pipe] = {
            "primary_cases": len(mine),
            "status": "REPORTED",
            "top1": len(hits) / len(mine),
            "severity_conditional_mae": float(
                np.mean(
                    [
                        abs(r["diagnosis"]["severity"]["point"] - r["truth"]["severity"])
                        for r in hits
                    ]
                )
            )
            if hits
            else None,
        }
    out["per_pipe"] = per_pipe
    top_p = np.array([r["diagnosis"]["probabilities"][r["diagnosis"]["ranking"][0]] for r in rows])
    hit = np.array(
        [r["diagnosis"]["ranking"][0] == r["truth"]["faulted_pipe"] for r in rows], dtype=float
    )
    bins = np.clip((top_p * 10).astype(int), 0, 9)
    out["expected_calibration_error"] = float(
        sum(
            abs(hit[bins == b].mean() - top_p[bins == b].mean()) * (bins == b).mean()
            for b in range(10)
            if (bins == b).any()
        )
    )

    if rows and "after" in rows[0]:

        def entropy(p):
            v = np.array([x for x in p.values() if x > 0])
            return float(-(v * np.log(v)).sum())

        before = np.array([entropy(r["diagnosis"]["probabilities"]) for r in rows])
        after = np.array([entropy(r["after"]["probabilities"]) for r in rows])
        after_random = np.array([entropy(r["after_random"]["probabilities"]) for r in rows])
        out["mean_entropy_before_nats"] = float(before.mean())
        out["measurement_entropy_reduction"] = (
            float((before.sum() - after.sum()) / before.sum()) if before.sum() > 0 else 0.0
        )
        diff = (before - after) - (before - after_random)
        out["measurement_against_random_mean"] = float(diff.mean())
        out["measurement_against_random_interval"] = bootstrap(diff, np.mean, seed)
        if primary:
            gain = top1(primary, "after") - top1(primary)
            out["measurement_top1_gain"] = float(gain.mean())
            out["measurement_top1_gain_interval"] = bootstrap(gain, np.mean, seed)
        kinds = [r["diagnosis"]["recommendation"]["kind"] for r in rows]
        out["recommended_types"] = {k: kinds.count(k) for k in sorted(set(kinds))}
        out["recommended_mean_duration_h"] = float(
            np.mean([r["diagnosis"]["recommendation"]["duration_h"] for r in rows])
        )
        out["recommended_share_production_interrupting"] = float(
            np.mean(
                [
                    r["diagnosis"]["recommendation"]["burden"] == "PRODUCTION_INTERRUPTING"
                    for r in rows
                ]
            )
        )
        rkinds = [r["random_action"]["kind"] for r in rows]
        out["random_types"] = {k: rkinds.count(k) for k in sorted(set(rkinds))}
        if "burden" in rows[0]:
            out["random_mean_duration_h"] = float(
                np.mean([r["burden"]["random_duration_h"] for r in rows])
            )
            out["random_share_production_interrupting"] = float(
                np.mean([r["random_action"]["kind"] == "SHUT_IN_TEST" for r in rows])
            )
            out["recommended_mean_deferred_sm3"] = float(
                np.mean([r["burden"]["recommended_deferred_sm3"] for r in rows])
            )
            out["random_mean_deferred_sm3"] = float(
                np.mean([r["burden"]["random_deferred_sm3"] for r in rows])
            )
            hours = np.array([r["burden"]["recommended_duration_h"] for r in rows])
            out["recommended_entropy_reduction_per_hour_nats"] = float(
                np.mean((before - after) / hours)
            )
        if "after_same_type" in rows[0]:
            same = np.array([entropy(r["after_same_type"]["probabilities"]) for r in rows])
            diff_same = (before - after) - (before - same)
            out["measurement_against_same_type_mean"] = float(diff_same.mean())
            out["measurement_against_same_type_interval"] = bootstrap(diff_same, np.mean, seed)
    return out
