"""Turn a run into shared events: the known onset, plus a minimal integration-proof rule.

The rule shows that sensor readings can reach the event contract. It isn't the Gate 5 detector,
and no accuracy is claimed for it. It reads sensor columns only, never simulator truth.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from packages.domain.events import EventDomain, EventKind, SharedEvent
from packages.domain.models import ProvenanceClass

from .config import IntegrationProofRule
from .simulate import SimulationRun, detector_view

EVENT_CLASS = "PROGRESSIVE_GATHERING_LINE_RESTRICTION"
ONSET_TRANSFORMATION = "aether.simulator.to_event@1"
RULE_TRANSFORMATION = "aether.integration_rule.to_event@1"


def first_sustained_exceedance(sensors: pd.DataFrame, rule: IntegrationProofRule) -> dict | None:
    """First sample of a run of readings above a baseline limit, or None."""
    if any(column.startswith("truth_") for column in sensors.columns):
        raise ValueError("the rule must not read simulator truth")
    offsets = sensors["offset_s"].to_numpy()
    values = sensors[rule.sensor_column].to_numpy()
    baseline = values[offsets < rule.baseline_duration_s]
    mean, std = float(baseline.mean()), float(baseline.std())
    limit = mean + rule.sigma_multiplier * std
    above = values > limit
    runs = np.convolve(above.astype(int), np.ones(rule.consecutive_samples, dtype=int), "valid")
    hits = np.flatnonzero(runs == rule.consecutive_samples)
    if len(hits) == 0:
        return None
    return {
        "offset_s": int(offsets[hits[0]]),
        "baseline_mean": round(mean, 3),
        "baseline_std": round(std, 3),
        "limit": round(limit, 3),
    }


def run_events(run: SimulationRun) -> list[SharedEvent]:
    config = run.config
    scenario = config.scenario
    common: dict[str, Any] = {
        "domain": EventDomain.AETHER_SYNTHETIC,
        "event_class": EVENT_CLASS,
        "source_system_id": "aether_synthetic",
        "scenario_id": scenario.scenario_id,
        "scenario_run_id": run.run_id,
        "target_asset_id": scenario.target_well,
        "affected_asset_id": scenario.restricted_segment,
        "provenance_class": ProvenanceClass.SYNTHETIC,
    }
    events = []
    if run.fault_onset_offset_s is not None:
        events.append(
            SharedEvent(
                event_id=f"{run.run_id}:known-onset",
                event_kind=EventKind.KNOWN_SYNTHETIC_ONSET,
                onset_offset_s=run.fault_onset_offset_s,
                evidence={
                    "basis": "Declared by the restriction schedule, not detected.",
                    "max_severity": config.restriction.max_severity,
                    "config_sha256": config.canonical_sha256(),
                    "random_seed": config.simulator.seed,
                },
                transformation_id=ONSET_TRANSFORMATION,
                **common,
            )
        )
    rule = config.integration_proof_rule
    hit = first_sustained_exceedance(detector_view(run.frame), rule)
    if hit is not None:
        events.append(
            SharedEvent(
                event_id=f"{run.run_id}:integration-rule",
                event_kind=EventKind.INTEGRATION_PROOF_RULE,
                onset_offset_s=hit["offset_s"],
                evidence={
                    "sensor": rule.sensor_column,
                    **{k: v for k, v in hit.items() if k != "offset_s"},
                    "note": "Integration proof on one seed. No accuracy is claimed.",
                },
                transformation_id=RULE_TRANSFORMATION,
                **common,
            )
        )
    return events
