"""Descriptive statistics."""

import numpy as np

from arrays.errors import ArrayError
from arrays.loading import as_array


def describe(values) -> dict:
    data = as_array(values)
    if data.size == 0:
        raise ArrayError("nothing to describe")
    return {
        "count": int(data.size),
        "mean": float(data.mean()),
        "std": float(data.std()),
        "min": float(data.min()),
        "max": float(data.max()),
        "product": float(np.product(data)),
        "all_positive": bool(np.alltrue(data > 0)),
    }


def zscore(values) -> np.ndarray:
    data = as_array(values)
    spread = data.std()
    if spread == 0:
        return np.zeros_like(data)
    return (data - data.mean()) / spread


def summary_text(values) -> str:
    """``n=3 mean=2.0 std=0.816 range=[1.0, 3.0]``: plain numbers, three decimals at most."""
    data = as_array(values)
    mean = np.round_(data.mean(), 3)
    spread = np.round_(data.std(), 3)
    return f"n={data.size} mean={mean!r} std={spread!r} range=[{data.min()!r}, {data.max()!r}]"


def fill_missing(values, fill=np.NaN) -> np.ndarray:
    """A copy with every NaN replaced by ``fill``."""
    data = as_array(values).copy()
    data[np.isnan(data)] = fill
    return data


def running_product(values) -> np.ndarray:
    return np.cumproduct(as_array(values))


def has_missing(values) -> bool:
    return bool(np.any(np.isnan(as_array(values))))
