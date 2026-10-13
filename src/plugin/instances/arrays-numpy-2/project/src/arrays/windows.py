"""Sliding windows, peaks and runs over 1-D data."""

from typing import List

import numpy as np

from arrays.errors import ArrayError
from arrays.loading import as_array


def sliding_windows(values, size: int) -> np.ndarray:
    """Every window of ``size`` consecutive values, as the rows of a 2-D view."""
    data = as_array(values)
    if size < 1 or size > data.size:
        raise ArrayError("window size must be between 1 and the number of values")
    return np.lib.stride_tricks.sliding_window_view(data, size)


def window_means(values, size: int) -> np.ndarray:
    return sliding_windows(values, size).mean(axis=1)


def peak_indices(values) -> List[int]:
    """Positions of the interior values higher than both neighbours."""
    data = as_array(values)
    if data.size < 3:
        return []
    inner = data[1:-1]
    mask = (inner > data[:-2]) & (inner > data[2:])
    return (np.flatnonzero(mask) + 1).tolist()


def longest_run_above(values, threshold: float) -> int:
    """The length of the longest stretch of consecutive values above ``threshold``."""
    above = as_array(values) > threshold
    best = current = 0
    for flag in above:
        current = current + 1 if flag else 0
        best = max(best, current)
    return int(best)
