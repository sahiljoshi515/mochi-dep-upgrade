"""Histograms, bins and membership."""

from typing import List, Tuple

import numpy as np

from arrays.loading import as_array


def histogram(values, bins: int = 5) -> Tuple[List[int], List[float]]:
    counts, edges = np.histogram(as_array(values), bins=bins)
    return counts.tolist(), edges.tolist()


def bin_labels(values, edges) -> np.ndarray:
    """Which bin each value falls in: 0 below the first edge, len(edges) at or past the last."""
    return np.digitize(as_array(values), as_array(edges))


def mask_members(values, allowed) -> np.ndarray:
    """A boolean mask: which values are among ``allowed``."""
    return np.in1d(as_array(values), as_array(allowed))


def count_in_bins(values, edges) -> List[int]:
    labels = bin_labels(values, edges)
    return [int(np.sum(labels == label)) for label in range(len(as_array(edges)) + 1)]


def quantiles(values, qs=(0.25, 0.5, 0.75)) -> List[float]:
    return np.quantile(as_array(values), list(qs), method="linear").tolist()
