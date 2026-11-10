"""Causal window features. A value depends only on rows at or before the end of its window."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STATS = ("mean", "std", "slope", "missing")
_CHUNK = 512


@dataclass(frozen=True)
class FeatureSpec:
    sensors: tuple[str, ...]
    window_samples: int
    stride_s: int
    sample_s: int

    @property
    def names(self) -> list[str]:
        return [f"{sensor}__{stat}" for sensor in self.sensors for stat in STATS]


def window_stats(windows: np.ndarray, sample_s: float) -> np.ndarray:
    """Statistics for an array shaped (windows, samples, sensors), ordered like FeatureSpec.names.

    A sensor with no reading gives NaN, not zero, and `missing` records the fraction absent.
    """
    count_windows, length, sensors = windows.shape
    present = ~np.isnan(windows)
    count = present.sum(axis=1)
    filled = np.where(present, windows, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=1) / count
        centered = np.where(present, windows - mean[:, None, :], 0.0)
        std = np.sqrt((centered**2).sum(axis=1) / count)
        time = np.arange(length, dtype=float)[None, :, None] * sample_s
        time_mean = (time * present).sum(axis=1) / count
        time_centered = np.where(present, time - time_mean[:, None, :], 0.0)
        denominator = (time_centered**2).sum(axis=1)
        slope = np.where(
            denominator > 0, (time_centered * centered).sum(axis=1) / denominator, np.nan
        )
    slope = np.where(count >= 2, slope, np.nan)
    missing = 1.0 - count / length
    output = np.empty((count_windows, sensors * len(STATS)), dtype=np.float32)
    output[:, 0::4], output[:, 1::4], output[:, 2::4], output[:, 3::4] = mean, std, slope, missing
    return output


def end_indices(times_s: np.ndarray, spec: FeatureSpec) -> np.ndarray:
    """Rows that end a window: anchored to absolute time, so overlapping instances share timestamps."""
    aligned = np.asarray(times_s, dtype=np.int64) % spec.stride_s == 0
    aligned[: spec.window_samples - 1] = False
    return np.flatnonzero(aligned)


def build_features(
    values: np.ndarray, times_s: np.ndarray, spec: FeatureSpec
) -> tuple[np.ndarray, np.ndarray]:
    """Features for one continuous series of shape (samples, sensors), and the row ending each window."""
    ends = end_indices(times_s, spec)
    if ends.size == 0:
        return np.empty((0, len(spec.names)), dtype=np.float32), ends
    view = np.lib.stride_tricks.sliding_window_view(values, spec.window_samples, axis=0)
    parts = []
    for start in range(0, ends.size, _CHUNK):
        chosen = ends[start : start + _CHUNK] - spec.window_samples + 1
        parts.append(window_stats(np.transpose(view[chosen], (0, 2, 1)), spec.sample_s))
    return np.concatenate(parts), ends


def columns_of(names: list[str], stat: str) -> np.ndarray:
    return np.array([i for i, name in enumerate(names) if name.endswith(f"__{stat}")])


def feature_frame(features: np.ndarray, spec: FeatureSpec) -> pd.DataFrame:
    return pd.DataFrame(features, columns=spec.names)
