"""Scenario definitions for the whole field. Physical, sensor, and communication faults stay separate."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .network_graph import REPO_ROOT
from .network_solver import NetworkState

CATALOG_PATH = REPO_ROOT / "config" / "scenarios" / "aether_field_scenarios.yaml"


class Category(StrEnum):
    NORMAL = "NORMAL"
    PHYSICAL_FAULT = "PHYSICAL_FAULT"
    SENSOR_FAULT = "SENSOR_FAULT"
    COMMUNICATION_FAULT = "COMMUNICATION_FAULT"
    PLANNED_OPERATION = "PLANNED_OPERATION"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Simulation(Strict):
    seed: int = Field(ge=0)
    interval_s: int = Field(gt=0)
    duration_s: int = Field(gt=0)
    simulated_epoch: str


class PhysicalFault(Strict):
    kind: Literal["SEGMENT_RESTRICTION", "COMPRESSOR_DERATE"]
    asset_id: str
    onset_s: int = Field(gt=0)
    full_s: int = Field(gt=0)
    max_severity: float | None = Field(default=None, gt=0, lt=1)
    final_fraction: float | None = Field(default=None, ge=0, lt=1)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.full_s <= self.onset_s:
            raise ValueError("full_s must come after onset_s")
        restriction = self.kind == "SEGMENT_RESTRICTION"
        if restriction != (self.max_severity is not None) or restriction == (
            self.final_fraction is not None
        ):
            raise ValueError(f"{self.kind} has the wrong parameters")
        return self

    def value_at(self, offset_s: int) -> float:
        progress = min(max((offset_s - self.onset_s) / (self.full_s - self.onset_s), 0.0), 1.0)
        if self.max_severity is not None:
            return self.max_severity * progress
        return 1.0 - (1.0 - (self.final_fraction or 0.0)) * progress


class SensorFault(Strict):
    kind: Literal["BIAS", "DRIFT"]
    tag: str
    onset_s: int = Field(gt=0)
    magnitude: float | None = None
    rate_per_day: float | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if (self.kind == "BIAS") != (self.magnitude is not None) or (self.kind == "DRIFT") != (
            self.rate_per_day is not None
        ):
            raise ValueError(f"{self.kind} has the wrong parameters")
        return self

    def error_at(self, offset_s: int) -> float:
        if offset_s < self.onset_s:
            return 0.0
        if self.magnitude is not None:
            return self.magnitude
        return (self.rate_per_day or 0.0) * (offset_s - self.onset_s) / 86400.0


class CommunicationFault(Strict):
    group: str
    onset_s: int = Field(gt=0)
    end_s: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_s <= self.onset_s:
            raise ValueError("end_s must come after onset_s")
        return self


class PlannedOperation(Strict):
    kind: Literal["CLOSE_VALVE", "STOP_COMPRESSOR", "SHUT_IN_WELL"]
    asset_id: str
    start_s: int = Field(gt=0)
    end_s: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError("end_s must come after start_s")
        return self

    def active(self, offset_s: int) -> bool:
        return self.start_s <= offset_s < self.end_s


class FieldScenario(Strict):
    scenario_id: str
    name: str
    version: int = Field(gt=0)
    category: Category
    target_asset_id: str
    affected_asset_id: str
    description: str
    physical_faults: list[PhysicalFault] = []
    sensor_faults: list[SensorFault] = []
    communication_faults: list[CommunicationFault] = []
    planned_operations: list[PlannedOperation] = []

    @model_validator(mode="after")
    def kinds_stay_separate(self) -> Self:
        """A scenario declares one kind of thing, so a sensor fault can't hide a physical change."""
        present = {
            Category.PHYSICAL_FAULT: self.physical_faults,
            Category.SENSOR_FAULT: self.sensor_faults,
            Category.COMMUNICATION_FAULT: self.communication_faults,
            Category.PLANNED_OPERATION: self.planned_operations,
        }
        for category, actions in present.items():
            if (category is self.category) != bool(actions):
                raise ValueError(f"{self.category} can't declare {category} actions this way")
        return self

    @property
    def changes_physics(self) -> bool:
        return self.category in (Category.PHYSICAL_FAULT, Category.PLANNED_OPERATION)

    @property
    def case_name(self) -> str:
        unplanned = (Category.PHYSICAL_FAULT, Category.SENSOR_FAULT, Category.COMMUNICATION_FAULT)
        return "fault" if self.category in unplanned else "nominal"

    @property
    def first_onset_s(self) -> int | None:
        onsets = (
            [f.onset_s for f in self.physical_faults]
            + [f.onset_s for f in self.sensor_faults]
            + [f.onset_s for f in self.communication_faults]
            + [p.start_s for p in self.planned_operations]
        )
        return min(onsets) if onsets else None

    def state_at(self, offset_s: int) -> NetworkState:
        severity = tuple(
            (f.asset_id, f.value_at(offset_s))
            for f in self.physical_faults
            if f.kind == "SEGMENT_RESTRICTION" and f.value_at(offset_s) > 0
        )
        fractions = {
            f.asset_id: f.value_at(offset_s)
            for f in self.physical_faults
            if f.kind == "COMPRESSOR_DERATE" and f.value_at(offset_s) < 1
        }
        closed: set[str] = set()
        shut_in: set[str] = set()
        for operation in self.planned_operations:
            if operation.active(offset_s):
                if operation.kind == "CLOSE_VALVE":
                    closed.add(operation.asset_id)
                elif operation.kind == "SHUT_IN_WELL":
                    shut_in.add(operation.asset_id)
                else:
                    fractions[operation.asset_id] = 0.0
        return NetworkState(
            severity,
            frozenset(closed),
            frozenset(shut_in),
            tuple(sorted(fractions.items())),
        )


class FieldCatalog(Strict):
    catalog_version: int = Field(gt=0)
    simulation: Simulation
    scenarios: list[FieldScenario]

    @model_validator(mode="after")
    def required_categories(self) -> Self:
        ids = [s.scenario_id for s in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        return self

    def get(self, scenario_id: str) -> FieldScenario:
        return next(s for s in self.scenarios if s.scenario_id == scenario_id)

    def sha256(self, scenario: FieldScenario, network_payload: dict) -> str:
        """The parameter set: network, simulation settings, and this scenario."""
        payload = {
            "network": network_payload,
            "simulation": self.simulation.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_catalog(path: Path = CATALOG_PATH) -> FieldCatalog:
    return FieldCatalog.model_validate(yaml.safe_load(path.read_text()))
