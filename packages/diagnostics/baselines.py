"""Baseline B1, frozen in the preregistration: rank pipes by the standardized residual of their observed
pressure drop against the nominal model solved at the measured suction pressure."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .forward import DP_NOISE_PA, PRESSURE_NOISE_PA, Forward

NONE = "NONE"


def b1_residual(
    telemetry: pd.DataFrame, prereg: dict[str, Any], current_hours: float = 2.0
) -> dict[str, Any]:
    offsets = telemetry["offset_s"].to_numpy()
    current = telemetry[offsets > int(prereg["inputs"]["diagnosis_time_s"]) - current_hours * 3600]
    probe = Forward({}, 1.6e6)
    suction = float(current["COMP-SUCTION.PT"].mean()) + probe.config.ambient.pressure_pa_abs
    forward = Forward({}, suction)
    nominal = forward.solve(None, 0.0)
    scores: dict[str, float] = {}
    for pipe in forward.pipes:
        edge = forward.graph.edges[pipe]
        predicted = forward.pipe_dp(nominal, pipe)
        if pipe.startswith("GS-"):
            values = current[f"{pipe}.DPT-NET"]
            noise = DP_NOISE_PA
        else:
            well = edge.source.removeprefix("WH:")
            header = edge.target
            values = current[f"{well}.PT-WH"] - current[f"{header}.PT-NET"]
            noise = PRESSURE_NOISE_PA * np.sqrt(2)
        values = values[np.isfinite(values)]
        if len(values) == 0:
            continue
        scores[pipe] = float((values.mean() - predicted) / (noise / np.sqrt(len(values))))
    ranked = sorted(scores, key=lambda p: -scores[p])
    ranking = ranked if scores and max(scores.values()) >= 3.0 else [NONE, *ranked]
    if NONE not in ranking:
        ranking.append(NONE)
    return {"ranking": ranking, "scores": scores}
