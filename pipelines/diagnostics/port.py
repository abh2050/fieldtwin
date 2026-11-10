"""The measurement port: the only path from a case's true state to a diagnosis.

It answers one requested measurement with a reading and nothing else, using the case's true
network state and the preregistered noise. Diagnosis code receives readings, never this object's
internals.
"""

from __future__ import annotations

import zlib
from typing import Any

import numpy as np

from packages.diagnostics.diagnose import Action, measurement_menu
from packages.diagnostics.forward import Forward, Sensor
from packages.scenario_engine.network_solver import NetworkModel, NetworkState, solve_network


class MeasurementPort:
    def __init__(self, truth: dict[str, Any], prereg: dict[str, Any]):
        state = truth["true_state"]
        self._seed = int(state["seed"])
        self._noise_multiplier = float(state["noise_multiplier"])
        self._menu = measurement_menu(prereg)
        self._forward = Forward(
            state["well_multipliers"],
            float(state["suction_setpoint_pa_abs"]),
            frozenset(state["shut_in_wells"]),
        )
        fractions = tuple((u, 0.0) for u in state["units_offline"])
        self._state = NetworkState(
            severity=tuple((p, float(s)) for p, s in state["severity"]),
            shut_in_wells=frozenset(state["shut_in_wells"]),
            compressor_fraction=fractions,
        )
        self.requests: list[Action] = []

    def _solve(self, extra_shut_in: str | None = None):
        state = self._state
        if extra_shut_in:
            state = NetworkState(
                state.severity,
                state.closed_valves,
                state.shut_in_wells | {extra_shut_in},
                state.compressor_fraction,
            )
        return solve_network(NetworkModel(self._forward.config, self._forward.graph), state)

    def read(self, action: Action, sensors: list[Sensor]) -> np.ndarray:
        """One reading. For a shut-in test, the given permanent sensors' 2-hour averages after shut-in."""
        self.requests.append(action)
        spec = self._menu[action.kind]
        rng = np.random.default_rng(
            [self._seed, zlib.crc32(f"port:{action.kind}:{action.target}".encode())]
        )
        if action.kind == "SHUT_IN_TEST":
            solution = self._solve(action.target)
            samples = spec.duration_h * 12
            noise = np.array([s.noise * self._noise_multiplier / np.sqrt(samples) for s in sensors])
            return self._forward.vector(solution, sensors) + rng.normal(0.0, noise)
        solution = self._solve()
        if action.kind == "PORTABLE_DP":
            value = self._forward.pipe_dp(solution, action.target)
        elif action.kind == "PRECISION_PT":
            value = solution.pressure_pa_abs[action.target] - self._forward.ambient
        else:
            value = solution.edge_flow_sm3_per_s[f"INFLOW:{action.target}"]
        assert spec.noise is not None
        return np.array([value + rng.normal(0.0, spec.noise)])
