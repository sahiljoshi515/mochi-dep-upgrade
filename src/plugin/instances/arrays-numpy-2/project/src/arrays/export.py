"""Arrays as text."""

from typing import List, Optional, Sequence

import numpy as np

from arrays.errors import ArrayError
from arrays.loading import as_array


def to_csv_lines(matrix, header: Optional[Sequence[str]] = None, places: int = 3) -> List[str]:
    """One CSV line per row, numbers rounded to ``places``; an optional header first."""
    data = np.round_(as_array(matrix), places)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.ndim != 2:
        raise ArrayError("only 1-D or 2-D data can be written")
    lines = [",".join(header)] if header else []
    lines += [",".join(f"{value:g}" for value in row) for row in data]
    return lines


def labels_array(labels: Sequence) -> np.ndarray:
    """``labels`` as an array of text."""
    return np.array([str(label) for label in labels], dtype=np.unicode_)


def is_text(array: np.ndarray) -> bool:
    return array.dtype.type in (np.string_, np.unicode_)


def to_bytes_rows(matrix, places: int = 3) -> List[bytes]:
    return [line.encode("ascii") for line in to_csv_lines(matrix, places=places)]
