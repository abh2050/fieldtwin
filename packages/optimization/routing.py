"""Shortest closed tour from the maintenance base through a set of sites, with OR-Tools.

Every tour is solved by OR-Tools. Small sets use its default local search, which stops on its own;
larger ones add guided local search under a time limit. Neither is a proven optimum, so the tests
compare OR-Tools with exhaustive enumeration on small sets, and the reports state the gap.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from functools import lru_cache

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# Above this many sites, guided local search runs until the time limit.
GUIDED_ABOVE = 8


def tour_length(order: Sequence[int], distance: Callable[[int, int], float]) -> float:
    """Length of base -> order... -> base, where 0 is the base."""
    stops = [0, *order, 0]
    return sum(distance(a, b) for a, b in itertools.pairwise(stops))


def exact_tour(n: int, distance: Callable[[int, int], float]) -> tuple[list[int], float]:
    """Exhaustive search over visiting sites 1..n-1 from base 0. A test oracle for small n."""
    best: tuple[list[int], float] = ([], 0.0)
    best_length = float("inf")
    for order in itertools.permutations(range(1, n)):
        length = tour_length(order, distance)
        if length < best_length:
            best, best_length = (list(order), length), length
    return best


def ortools_tour(
    n: int, distance: Callable[[int, int], float], time_limit_s: float
) -> tuple[list[int], float]:
    if n <= 1:
        return [], 0.0
    scale = 1000  # OR-Tools works in integers; distances are kept to the millimetre.
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cost(i: int, j: int) -> int:
        return int(round(distance(manager.IndexToNode(i), manager.IndexToNode(j)) * scale))

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(cost))
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    if n > GUIDED_ABOVE:
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError("OR-Tools found no tour")
    order, index = [], routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:
            order.append(node)
        index = solution.Value(routing.NextVar(index))
    return order, tour_length(order, distance)


class Router:
    """Tours between named sites, cached by the set of sites visited."""

    def __init__(self, distance_m: Callable[[str, str], float], base: str, time_limit_s: float):
        self.distance_m = distance_m
        self.base = base
        self.time_limit_s = time_limit_s
        self.solver_calls = 0
        self._solve = lru_cache(maxsize=None)(self._solve_uncached)

    def _solve_uncached(self, sites: frozenset[str]) -> tuple[tuple[str, ...], float]:
        names = [self.base, *sorted(sites)]

        def distance(i: int, j: int) -> float:
            return self.distance_m(names[i], names[j])

        self.solver_calls += 1
        order, length = ortools_tour(len(names), distance, self.time_limit_s)
        return tuple(names[i] for i in order), length

    def tour(self, sites: Sequence[str]) -> tuple[tuple[str, ...], float]:
        """Order and length in metres of the closed tour from the base through every site."""
        unique = frozenset(sites) - {self.base}
        if not unique:
            return (), 0.0
        return self._solve(unique)

    def out_and_back(self, site: str) -> float:
        return 2 * self.distance_m(self.base, site)
