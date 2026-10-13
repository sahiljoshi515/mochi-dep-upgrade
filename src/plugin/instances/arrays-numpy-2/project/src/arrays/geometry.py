"""Plane geometry on point arrays."""

from typing import Tuple

import numpy as np

from arrays.errors import ArrayError
from arrays.loading import as_array


def turn_direction(p, q, r) -> int:
    """1 for a left (counter-clockwise) turn p -> q -> r, -1 for a right turn, 0 for a straight line."""
    first = as_array(q) - as_array(p)
    second = as_array(r) - as_array(q)
    return int(np.sign(np.cross(first, second)))


def polygon_area(points) -> float:
    """The area of a simple polygon given by its vertices in order (the shoelace formula)."""
    pts = as_array(points)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 3:
        raise ArrayError("a polygon needs at least three 2-D points")
    x, y = pts[:, 0], pts[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def reduce_axis(matrix, axis: int, reducer=np.sum) -> np.ndarray:
    """``reducer`` along ``axis``; an ArrayError names an axis the data does not have."""
    data = as_array(matrix)
    try:
        return reducer(data, axis=axis)
    except np.AxisError as error:
        raise ArrayError(f"axis {axis} is out of bounds for {data.ndim}-D data") from error


def bounding_box(points) -> Tuple[np.ndarray, np.ndarray]:
    pts = as_array(points)
    return pts.min(axis=0), pts.max(axis=0)


def centroid(points) -> np.ndarray:
    return as_array(points).mean(axis=0)
