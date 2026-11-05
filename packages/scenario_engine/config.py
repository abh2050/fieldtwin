"""Typed, validated simulator configuration. Unknown keys and unphysical values are refused."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = REPO_ROOT / "config" / "scenarios" / "aether_fault_001.yaml"
UNIVERSAL_GAS_CONSTANT = 8.314462618  # J/(mol K)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scenario(Strict):
    scenario_id: str
    name: str
    version: int = Field(gt=0)
    target_well: str
    restricted_segment: str
    provenance_class: str = Field(pattern="^SYNTHETIC$")
    disclosure: str


class Simulator(Strict):
    name: str
    version: int = Field(gt=0)
    time_model: str = Field(pattern="^quasi_steady$")
    seed: int = Field(ge=0)


class Gas(Strict):
    molar_mass_kg_per_mol: float = Field(gt=0)
    compressibility_factor: float = Field(gt=0, le=1.2)
    temperature_k: float = Field(gt=0)
    dynamic_viscosity_pa_s: float = Field(gt=0)
    heat_capacity_ratio: float = Field(gt=1)

    @property
    def specific_gas_constant(self) -> float:
        return UNIVERSAL_GAS_CONSTANT / self.molar_mass_kg_per_mol


class StandardConditions(Strict):
    pressure_pa_abs: float = Field(gt=0)
    temperature_k: float = Field(gt=0)


class Ambient(Strict):
    pressure_pa_abs: float = Field(gt=0)


class Well(Strict):
    asset_id: str
    shut_in_wellhead_pressure_pa_abs: float = Field(gt=0)
    deliverability_coefficient: float = Field(gt=0)
    deliverability_exponent: float = Field(ge=0.5, le=1.0)


class GatheringSegment(Strict):
    asset_id: str
    length_m: float = Field(gt=0)
    internal_diameter_m: float = Field(gt=0)
    darcy_friction_factor: float = Field(gt=0)
    restricted_length_m: float = Field(gt=0)
    downstream_boundary_pressure_pa_abs: float = Field(gt=0)

    @model_validator(mode="after")
    def restriction_fits_segment(self) -> Self:
        if self.restricted_length_m >= self.length_m:
            raise ValueError("restricted_length_m must be shorter than the segment")
        return self


class Sampling(Strict):
    interval_s: int = Field(gt=0)
    duration_s: int = Field(gt=0)


class Restriction(Strict):
    onset_offset_s: int = Field(gt=0)
    full_severity_offset_s: int = Field(gt=0)
    max_severity: float = Field(gt=0, lt=1)
    severity_limit: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def schedule_is_ordered(self) -> Self:
        if self.full_severity_offset_s <= self.onset_offset_s:
            raise ValueError("full severity must come after onset")
        if self.max_severity > self.severity_limit:
            raise ValueError("max_severity exceeds severity_limit")
        return self


class Range(Strict):
    min: float
    max: float


class OperatingLimits(Strict):
    max_mach_number: float = Field(gt=0, le=1)
    min_reynolds_number: float = Field(gt=0)
    nominal_flow_sm3_per_s: Range
    nominal_wellhead_pressure_pa_abs: Range


class Sensor(Strict):
    tag: str
    column: str
    asset_id: str
    equipment_class_id: str
    measurement_definition_id: str
    truth_column: str
    quantity: str
    reference: str = Field(pattern="^(GAUGE|DIFFERENTIAL|ABSOLUTE|NOT_APPLICABLE)$")
    unit: str
    display_unit: str
    noise_std: float = Field(ge=0)


class IntegrationProofRule(Strict):
    sensor_column: str
    baseline_duration_s: int = Field(gt=0)
    sigma_multiplier: float = Field(gt=0)
    consecutive_samples: int = Field(gt=0)


class Case(Strict):
    restriction_enabled: bool


class ScenarioConfig(Strict):
    scenario: Scenario
    simulator: Simulator
    gas: Gas
    standard_conditions: StandardConditions
    ambient: Ambient
    well: Well
    gathering_segment: GatheringSegment
    sampling: Sampling
    restriction: Restriction
    operating_limits: OperatingLimits
    sensors: list[Sensor] = Field(min_length=1)
    expected_invariants: list[str] = Field(min_length=1)
    integration_proof_rule: IntegrationProofRule
    cases: dict[str, Case]

    @model_validator(mode="after")
    def physically_feasible(self) -> Self:
        source = self.well.shut_in_wellhead_pressure_pa_abs
        sink = self.gathering_segment.downstream_boundary_pressure_pa_abs
        if source <= sink:
            raise ValueError("shut-in pressure must exceed downstream pressure for forward flow")
        if sink <= self.ambient.pressure_pa_abs:
            raise ValueError("downstream pressure must exceed ambient")
        if self.restriction.full_severity_offset_s > self.sampling.duration_s:
            raise ValueError("the restriction schedule must fit inside the simulated duration")
        if self.integration_proof_rule.baseline_duration_s > self.restriction.onset_offset_s:
            raise ValueError("the rule baseline must end before fault onset")
        return self

    def canonical_sha256(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()


def load_config(path: Path = SCENARIO_PATH, **overrides: Any) -> ScenarioConfig:
    data = yaml.safe_load(path.read_text())
    data.update(overrides)
    return ScenarioConfig.model_validate(data)
