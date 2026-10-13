import pytest

from arrays import ArrayError, area_under, as_array, detrend, is_text, labels_array, mask_members, parse_matrix, reduce_axis, rescale, stack_rows, to_bytes_rows, turn_direction


def test_turn_direction_signs():
    assert turn_direction([0, 0], [1, 0], [1, 1]) == 1
    assert turn_direction([0, 0], [1, 0], [1, -1]) == -1
    assert turn_direction([0, 0], [1, 1], [2, 2]) == 0


def test_area_under_and_stacking():
    assert area_under([0, 1, 2], [0, 1, 0]) == 1.0
    assert area_under([0, 2], [3, 3]) == 6.0
    stacked = stack_rows([[1, 2], [3, 4], (5, 6)])
    assert stacked.shape == (3, 2) and stacked.tolist()[2] == [5.0, 6.0]
    with pytest.raises(ArrayError):
        stack_rows([[1, 2], [3]])


def test_mask_members_and_rescale():
    assert mask_members([1, 2, 3, 4], [2, 4, 6]).tolist() == [False, True, False, True]
    assert rescale([2, 4, 6]).tolist() == [0.0, 0.5, 1.0]
    assert rescale([1, 1], low=5.0).tolist() == [5.0, 5.0]
    assert [round(value, 6) for value in detrend([1, 2, 3]).tolist()] == [0.0, 0.0, 0.0]


def test_reduce_axis_reports_a_bad_axis():
    matrix = parse_matrix("1 2\n3 4\n")
    assert reduce_axis(matrix, 0).tolist() == [4.0, 6.0]
    assert reduce_axis(matrix, 1).tolist() == [3.0, 7.0]
    with pytest.raises(ArrayError, match="axis 2"):
        reduce_axis(matrix, 2)


def test_text_arrays_and_bytes_rows():
    labels = labels_array(["a", 7, "c"])
    assert labels.tolist() == ["a", "7", "c"] and labels.dtype.kind == "U"
    assert is_text(labels) is True
    assert is_text(as_array([1.0])) is False
    assert to_bytes_rows([[1.5, 2.25]]) == [b"1.5,2.25"]
