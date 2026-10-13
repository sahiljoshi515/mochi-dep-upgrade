"""Smoothing, integration and simple transforms of 1-D data."""

import numpy as np

from arrays.errors import ArrayError
from arrays.loading import as_array


def moving_average(values, window: int) -> np.ndarray:
    data = as_array(values)
    if window < 1 or window > data.size:
        raise ArrayError("window must be between 1 and the number of values")
    return np.convolve(data, np.ones(window) / window, mode="valid")


def area_under(x, y) -> float:
    """The area under the curve ``y(x)`` by the trapezoid rule."""
    return float(np.trapz(as_array(y), as_array(x)))


def stack_rows(rows) -> np.ndarray:
    """Equal-length 1-D sequences as the rows of a 2-D array."""
    arrays = [as_array(row) for row in rows]
    if not arrays or len({array.size for array in arrays}) != 1:
        raise ArrayError("rows must be non-empty and of one length")
    return np.row_stack(arrays)


def detrend(values) -> np.ndarray:
    """The values minus their least-squares line."""
    data = as_array(values)
    x = np.arange(data.size, dtype=float)
    slope, intercept = np.polyfit(x, data, 1)
    return data - (slope * x + intercept)


def rescale(values, low: float = 0.0, high: float = 1.0) -> np.ndarray:
    """Min-max scaling into ``[low, high]``; constant data maps to ``low``."""
    data = as_array(values)
    span = data.max() - data.min()
    if span == 0:
        return np.full_like(data, low)
    return low + (data - data.min()) / span * (high - low)
