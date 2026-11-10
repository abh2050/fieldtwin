"""Great-circle distances in metres.

Well coordinates are NAD83 and Carbon Mapper coordinates are WGS84. The two differ by about a metre
here, far below the 3 to 60 m pixel size of the plume instruments, so they are compared directly.
"""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Distance between points, broadcasting like numpy."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def distance_matrix(
    lats_a: np.ndarray, lons_a: np.ndarray, lats_b: np.ndarray, lons_b: np.ndarray
) -> np.ndarray:
    """Rows are points in a, columns are points in b."""
    return haversine_m(lats_a[:, None], lons_a[:, None], lats_b[None, :], lons_b[None, :])
