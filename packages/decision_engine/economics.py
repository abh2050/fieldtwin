"""Modeled comparison of fixed, risk-based, and route-optimized inspection scheduling.

Every number this produces is a modeled scenario estimate for a fictional facility under declared
assumptions (config/decision/economics.yaml). It is not a realized or expected saving for anyone.

Each replicate draws one year of faults and false alarms. All three strategies then face the same draw
(common random numbers), so differences between them come from scheduling, not from luck.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

HOURS_PER_DAY = 24.0
STRATEGIES = ("FIXED", "RISK_BASED", "ROUTE_OPTIMIZED")


@dataclass(frozen=True)
class Asset:
    asset_id: str
    asset_class: str  # well, flowline, gathering_segment, compressor
    site: str
    group: str  # pad or station, for mislocalized dispatches
    flow_mcf_per_day: float


@dataclass(frozen=True)
class DetectorStats:
    """Gate 5 held-out behaviour of the selected detector, by category."""

    detect_share: dict[str, float]
    delay_quartiles_h: dict[str, tuple[float, float]]
    false_alarms_per_hour: float


@dataclass
class Fault:
    asset: Asset
    physical: bool
    onset_h: float
    alarm_h: float | None
    localized: bool
    repaired_h: float | None = None
    found: bool = False


@dataclass
class Job:
    ready_h: float
    site: str
    kind: str  # ALARM, FALSE_ALARM


@dataclass
class Totals:
    travel_km: float = 0.0
    labor_h: float = 0.0
    site_visits: int = 0
    alarm_trips: int = 0
    trips_finding_nothing: int = 0
    physical_faults: int = 0
    physical_repaired: int = 0
    repair_hours: list[float] = field(default_factory=list)
    deferred_mcf: float = 0.0


def draw_year(
    assets: Sequence[Asset],
    sites: Sequence[str],
    cfg: dict[str, Any],
    stats: DetectorStats,
    rng: np.random.Generator,
) -> tuple[list[Fault], list[Job]]:
    horizon_h = cfg["horizon_days"] * HOURS_PER_DAY
    faults: list[Fault] = []
    groups: dict[str, list[str]] = {}
    for asset in assets:
        groups.setdefault(asset.group, []).append(asset.site)
    for asset in assets:
        rate = cfg["fault_rate_per_asset_year"][asset.asset_class] * cfg["horizon_days"] / 365
        for _ in range(rng.poisson(rate)):
            physical = rng.random() >= cfg["sensor_fault_share"]
            category = cfg["category_for"][asset.asset_class if physical else "sensor"]
            onset = rng.uniform(0, horizon_h)
            alarm = None
            if rng.random() < stats.detect_share[category]:
                low, high = stats.delay_quartiles_h[category]
                alarm = onset + rng.uniform(low, high)
            faults.append(
                Fault(asset, physical, onset, alarm, rng.random() < cfg["localization_correct"])
            )
    false_alarms = [
        Job(ready_h=float(t), site=str(rng.choice(sites)), kind="FALSE_ALARM")
        for t in rng.uniform(0, horizon_h, rng.poisson(stats.false_alarms_per_hour * horizon_h))
    ]
    wrong_site = {
        id(f): str(rng.choice([s for s in groups[f.asset.group] if s != f.asset.site] or sites))
        for f in faults
    }
    jobs = [
        Job(
            ready_h=f.alarm_h + 0.0,
            site=f.asset.site if f.localized else wrong_site[id(f)],
            kind="ALARM",
        )
        for f in faults
        if f.alarm_h is not None
    ]
    return faults, sorted(jobs + false_alarms, key=lambda j: j.ready_h)


def simulate(
    strategy: str,
    faults: list[Fault],
    alarm_jobs: list[Job],
    sites: Sequence[str],
    cfg: dict[str, Any],
    distance_m: Callable[[str, str], float],
    tour: Callable[[Sequence[str]], tuple[tuple[str, ...], float]],
    base: str,
    rng: np.random.Generator,
) -> Totals:
    """Run one strategy through one drawn year. Faults are copied so strategies don't interact."""
    faults = [Fault(f.asset, f.physical, f.onset_h, f.alarm_h, f.localized) for f in faults]
    plan = cfg["strategies"][strategy]
    horizon_h = cfg["horizon_days"] * HOURS_PER_DAY
    speed = cfg["travel"]["speed_km_per_h"]
    road = cfg["travel"]["road_factor"]
    on_site = cfg["inspection"]["on_site_hours"]
    capacity = cfg["labor"]["crews"] * cfg["labor"]["hours_per_day"]
    cycle = plan.get("cycle_days", plan.get("fallback_cycle_days"))
    approval = plan.get("approval_delay_h", 0.0)
    totals = Totals()
    pending = (
        []
        if strategy == "FIXED"
        else [Job(j.ready_h + approval, j.site, j.kind) for j in alarm_jobs]
    )
    round_queue: list[str] = []

    def path_m(stops: Sequence[str]) -> float:
        points = [base, *stops, base]
        return road * sum(distance_m(a, b) for a, b in zip(points, points[1:], strict=False))

    def visit(site: str, at_h: float) -> bool:
        found_any = False
        for f in faults:
            if f.asset.site != site or f.repaired_h is not None or f.onset_h > at_h:
                continue
            if not f.physical or rng.random() < cfg["inspection"]["finds_physical_fault"]:
                f.repaired_h = at_h + (
                    cfg["inspection"]["repair_days"] * HOURS_PER_DAY if f.physical else 0.0
                )
                f.found = True
                found_any = True
        totals.site_visits += 1
        return found_any

    for day in range(cfg["horizon_days"]):
        start_h = day * HOURS_PER_DAY
        if day % cycle == 0:
            round_queue.extend(s for s in sites if s not in round_queue)
        due = [j for j in pending if j.ready_h <= start_h + HOURS_PER_DAY]
        hours_left = capacity
        midday = start_h + 12.0

        if strategy == "ROUTE_OPTIMIZED":
            # Alarm sites first, then the round, while the optimized tour still fits in the day.
            chosen: list[str] = []
            for site in [j.site for j in due] + list(round_queue):
                if site in chosen:
                    continue
                trial = chosen + [site]
                _, length = tour(trial)
                if road * length / 1000 / speed + on_site * len(trial) <= capacity:
                    chosen = trial
                elif len(chosen) * on_site >= capacity - on_site:
                    break
            if chosen:
                _, length = tour(chosen)
                km = road * length / 1000
                totals.travel_km += km
                totals.labor_h += km / speed + on_site * len(chosen)
                for site in chosen:
                    found = visit(site, midday)
                    served = [j for j in due if j.site == site]
                    totals.alarm_trips += len(served)
                    totals.trips_finding_nothing += sum(1 for _ in served) if not found else 0
                    pending = [j for j in pending if j not in served]
                    if site in round_queue:
                        round_queue.remove(site)
            continue

        for job in due:  # Separate out-and-back trips, in order of readiness.
            hours = road * 2 * distance_m(base, job.site) / 1000 / speed + on_site
            if hours > hours_left:
                break
            hours_left -= hours
            totals.travel_km += road * 2 * distance_m(base, job.site) / 1000
            totals.labor_h += hours
            totals.alarm_trips += 1
            if not visit(job.site, midday):
                totals.trips_finding_nothing += 1
            pending.remove(job)
            if job.site in round_queue:
                round_queue.remove(job.site)
        stops: list[str] = []
        for site in list(round_queue):  # The round continues in fixed order with the hours left.
            trial = stops + [site]
            hours = path_m(trial) / 1000 / speed + on_site * len(trial)
            if hours > hours_left:
                break
            stops = trial
        if stops:
            km = path_m(stops) / 1000
            totals.travel_km += km
            totals.labor_h += km / speed + on_site * len(stops)
            for site in stops:
                visit(site, midday)
                round_queue.remove(site)

    for f in faults:
        if not f.physical:
            continue
        totals.physical_faults += 1
        end = min(f.repaired_h, horizon_h) if f.repaired_h is not None else horizon_h
        totals.deferred_mcf += (
            f.asset.flow_mcf_per_day
            * cfg["production"]["deferred_share_while_faulted"]
            * max(end - f.onset_h, 0.0)
            / HOURS_PER_DAY
        )
        if f.repaired_h is not None and f.repaired_h <= horizon_h:
            totals.physical_repaired += 1
            totals.repair_hours.append(f.repaired_h - f.onset_h)
    return totals


def costs(totals: Totals, cfg: dict[str, Any]) -> dict[str, float]:
    travel = totals.travel_km * cfg["travel"]["cost_per_km"]
    labor = totals.labor_h * cfg["labor"]["cost_per_hour"]
    deferred = totals.deferred_mcf * cfg["production"]["gas_price_per_mcf"]
    return {
        "travel": travel,
        "labor": labor,
        "deferred_production": deferred,
        "total": travel + labor + deferred,
        "travel_km": totals.travel_km,
        "labor_h": totals.labor_h,
        "site_visits": float(totals.site_visits),
        "alarm_trips": float(totals.alarm_trips),
        "trips_finding_nothing": float(totals.trips_finding_nothing),
        "physical_faults": float(totals.physical_faults),
        "physical_repaired": float(totals.physical_repaired),
        "mean_hours_to_repair": float(np.mean(totals.repair_hours))
        if totals.repair_hours
        else float("nan"),
        "deferred_mcf": totals.deferred_mcf,
    }
