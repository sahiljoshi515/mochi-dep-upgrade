import pytest

from arrays import ArrayError
from arrays.windows import longest_run_above, peak_indices, sliding_windows, window_means


def test_sliding_windows_and_means():
    windows = sliding_windows([1, 2, 3, 4], 2)
    assert windows.shape == (3, 2) and windows.tolist() == [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]]
    assert window_means([1, 2, 3, 4], 3).tolist() == [2.0, 3.0]
    with pytest.raises(ArrayError):
        sliding_windows([1, 2], 3)


def test_peaks_and_runs():
    assert peak_indices([1, 3, 2, 5, 4, 4]) == [1, 3]
    assert peak_indices([1, 2]) == []
    assert longest_run_above([1, 5, 6, 2, 7, 8, 9, 0], 4) == 3
    assert longest_run_above([1, 1], 4) == 0
