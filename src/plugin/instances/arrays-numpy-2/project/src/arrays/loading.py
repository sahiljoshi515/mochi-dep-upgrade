"""Getting data into arrays."""

from typing import Sequence

import numpy as np

from arrays.errors import ArrayError


def as_array(values) -> np.ndarray:
    """A float64 array of ``values`` (a list, a tuple or an array); an array is used as it is."""
    return np.array(values, dtype=np.float_, copy=False)


def from_records(rows: Sequence[dict], fields: Sequence[str]) -> np.ndarray:
    """A 2-D float array with one row per record and the columns in ``fields`` order."""
    if not rows:
        raise ArrayError("no records")
    try:
        return np.asfarray([[row[field] for field in fields] for row in rows])
    except KeyError as error:
        raise ArrayError(f"record lacks the field {error.args[0]!r}") from None


def parse_matrix(text: str) -> np.ndarray:
    """Rows of whitespace-separated numbers, one per line."""
    rows = [[float(cell) for cell in line.split()] for line in text.strip().splitlines() if line.strip()]
    if not rows:
        raise ArrayError("no rows")
    if len({len(row) for row in rows}) != 1:
        raise ArrayError("ragged rows")
    return np.array(rows, dtype=np.float_)


def column(matrix: np.ndarray, index: int) -> np.ndarray:
    """One column of a 2-D array, as its own contiguous array."""
    if matrix.ndim != 2:
        raise ArrayError("a column needs a 2-D array")
    return np.ascontiguousarray(matrix[:, index])
