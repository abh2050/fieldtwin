"""Run simulator work in a child process with a hard timeout and a stack dump.

This protects against hangs. It doesn't explain the single unexplained Gate 4 hang, whose cause was
never determined.
"""

from __future__ import annotations

import faulthandler
import importlib
import json
import multiprocessing as mp
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass
from enum import StrEnum
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, TextIO

from .network_solver import InfeasibleNetworkState, SolverDidNotConverge


class Outcome(StrEnum):
    OK = "OK"
    SOLVER_NONCONVERGENCE = "SOLVER_NONCONVERGENCE"
    INFEASIBLE_STATE = "INFEASIBLE_STATE"
    ENVELOPE_REFUSED = "ENVELOPE_REFUSED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    CRASH = "CRASH"


@dataclass(frozen=True)
class ExecutionReport:
    label: str
    outcome: Outcome
    elapsed_s: float
    timeout_s: float
    result: dict[str, Any] | None
    detail: str | None
    stack: str | None

    def to_dict(self) -> dict:
        return {**asdict(self), "outcome": self.outcome.value}


def _classify(error: BaseException) -> Outcome:
    # Imported here so a child that only runs Gate 4 work doesn't load the benchmark.
    from .benchmark_runs import CaseRefused

    if isinstance(error, SolverDidNotConverge):
        return Outcome.SOLVER_NONCONVERGENCE
    if isinstance(error, CaseRefused):
        return Outcome.ENVELOPE_REFUSED
    if isinstance(error, InfeasibleNetworkState):
        return Outcome.INFEASIBLE_STATE
    return Outcome.CRASH


def _child(target: str, kwargs: dict, connection: Connection, stack_path: str, timeout_s: float) -> None:
    with open(stack_path, "w") as stack_file:
        # Fires just before the parent gives up, so the parent can read where the child was.
        faulthandler.dump_traceback_later(max(timeout_s * 0.9, 0.05), file=stack_file, exit=False)
        try:
            module, _, name = target.partition(":")
            function = getattr(importlib.import_module(module), name)
            connection.send((Outcome.OK.value, function(**kwargs), None))
        except BaseException as error:  # noqa: BLE001
            connection.send((_classify(error).value, None, f"{type(error).__name__}: {error}\n{traceback.format_exc()}"))
        finally:
            faulthandler.cancel_dump_traceback_later()
            connection.close()


def log_event(stream: TextIO | None, **fields: Any) -> None:
    """One JSON line per step, so a stalled run shows how far it got."""
    if stream is not None:
        stream.write(json.dumps({"time": round(time.time(), 3), **fields}, sort_keys=True) + "\n")
        stream.flush()


def run_with_timeout(target: str, kwargs: dict, *, timeout_s: float, label: str, log: TextIO | None = None) -> ExecutionReport:
    """Run `module:function(**kwargs)` in a fresh process. The child is killed at the timeout."""
    context = mp.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    with tempfile.TemporaryDirectory() as folder:
        stack_path = str(Path(folder) / "stack.txt")
        process = context.Process(target=_child, args=(target, kwargs, send, stack_path, timeout_s), daemon=True)
        started = time.monotonic()
        log_event(log, event="start", label=label, timeout_s=timeout_s)
        process.start()
        send.close()
        message = None
        if receive.poll(timeout_s):
            try:
                message = receive.recv()
            except EOFError:
                message = None
        elapsed = time.monotonic() - started
        timed_out = message is None and process.is_alive()
        if process.is_alive():
            if message is not None:
                process.join(5.0)
            if process.is_alive():
                process.kill()
        process.join()
        stack = Path(stack_path).read_text() if Path(stack_path).exists() else ""
        receive.close()
    if timed_out:
        report = ExecutionReport(label, Outcome.EXECUTION_TIMEOUT, elapsed, timeout_s, None, f"killed after {timeout_s} s", stack or None)
    elif message is None:
        report = ExecutionReport(label, Outcome.CRASH, elapsed, timeout_s, None, f"process exited with code {process.exitcode} and sent no result", stack or None)
    else:
        outcome, result, detail = message
        report = ExecutionReport(label, Outcome(outcome), elapsed, timeout_s, result, detail, None)
    log_event(log, event="finish", label=label, outcome=report.outcome.value, elapsed_s=round(elapsed, 3))
    return report


# Targets run inside the child. Each returns plain data.
def gate4_scenario(scenario_id: str) -> dict:
    from .field_simulation import simulate_by_id

    run = simulate_by_id(scenario_id)
    return {
        "sha256": run.canonical_sha256(),
        "max_newton_iterations": int(run.truth["diag_newton_iterations"].max()),
        "max_active_set_passes": int(run.truth["diag_active_set_passes"].max()),
        "max_relative_residual": float(run.truth["diag_relative_residual"].max()),
    }


def propagation_comparison() -> dict:
    """The kind of work that was running when the unexplained Gate 4 hang occurred."""
    from .propagation import PROPAGATION_CASES, compare

    rows = sum(len(compare(case)) for case in PROPAGATION_CASES)
    return {"rows": rows}


def forced_nonconvergence() -> dict:
    """A real solve with too few iterations allowed, used to prove the failure is classified."""
    from .field_simulation import default_setup
    from .network_solver import NetworkModel, NetworkState, solve_network

    config, graph, _, _, _ = default_setup()
    starved = config.model_copy(update={"solver": config.solver.model_copy(update={"max_iterations": 1, "relative_residual_tolerance": 1e-30})})
    solve_network(NetworkModel(starved, graph), NetworkState())
    return {}


def forced_infeasible() -> dict:
    from .field_simulation import default_setup
    from .network_solver import NetworkState, solve_network

    solve_network(default_setup()[2], NetworkState(closed_valves=frozenset({"NOT-A-VALVE"})))
    return {}


def forced_hang() -> dict:
    """Sleeps past any test timeout, used to prove the timeout path works."""
    time.sleep(3600)
    return {}


def forced_crash() -> dict:
    import os

    os._exit(3)
