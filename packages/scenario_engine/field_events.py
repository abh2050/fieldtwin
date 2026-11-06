"""Known scenario events in the shared contract. They are declared by configuration, not detected."""

from __future__ import annotations

from packages.domain.events import EventDomain, EventKind, SharedEvent
from packages.domain.models import ProvenanceClass

from .field_simulation import FieldRun, default_setup

TRANSFORMATION = "aether.field_simulator.to_event@1"
_CLASSES = {
    "SEGMENT_RESTRICTION": "PROGRESSIVE_GATHERING_LINE_RESTRICTION",
    "COMPRESSOR_DERATE": "COMPRESSOR_CAPACITY_REDUCTION",
    "BIAS": "SENSOR_BIAS",
    "DRIFT": "SENSOR_DRIFT",
    "CLOSE_VALVE": "PLANNED_VALVE_CLOSURE",
    "STOP_COMPRESSOR": "PLANNED_COMPRESSOR_STOP",
    "SHUT_IN_WELL": "PLANNED_WELL_SHUT_IN",
}


def field_events(run: FieldRun) -> list[SharedEvent]:
    scenario = run.scenario
    sensors = {s.tag: s for s in default_setup()[4]}
    declared = (
        [("PHYSICAL", _CLASSES[f.kind], f.asset_id, f.onset_s) for f in scenario.physical_faults]
        + [
            ("SENSOR", _CLASSES[f.kind], sensors[f.tag].asset_id, f.onset_s)
            for f in scenario.sensor_faults
        ]
        + [
            ("COMMUNICATION", "COMMUNICATION_DROPOUT", f.group, f.onset_s)
            for f in scenario.communication_faults
        ]
        + [
            ("PLANNED", _CLASSES[p.kind], p.asset_id, p.start_s)
            for p in scenario.planned_operations
        ]
    )
    return [
        SharedEvent(
            event_id=f"{run.run_id}:known:{index}",
            domain=EventDomain.AETHER_SYNTHETIC,
            event_kind=EventKind.KNOWN_SYNTHETIC_ONSET,
            event_class=event_class,
            source_system_id="aether_synthetic",
            scenario_id=scenario.scenario_id,
            scenario_run_id=run.run_id,
            target_asset_id=scenario.target_asset_id,
            affected_asset_id=asset,
            onset_offset_s=onset,
            evidence={
                "fault_domain": domain,
                "basis": "Declared by the scenario configuration, not detected.",
                "parameter_set_sha256": run.parameter_set_sha256,
                "random_seed": run.seed,
            },
            provenance_class=ProvenanceClass.SYNTHETIC,
            transformation_id=TRANSFORMATION,
        )
        for index, (domain, event_class, asset, onset) in enumerate(declared)
    ]
