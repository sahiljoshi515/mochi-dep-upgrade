import pytest

from arrays import ArrayError, as_array, describe, fill_missing, from_records, has_missing, running_product, summary_text


def test_as_array_accepts_lists_and_shares_arrays():
    made = as_array([1, 2, 3])
    assert made.tolist() == [1.0, 2.0, 3.0] and made.dtype.name == "float64"
    assert as_array((4, 5)).tolist() == [4.0, 5.0]
    same = as_array(made)
    same[0] = 9.0
    assert made[0] == 9.0


def test_from_records_orders_columns_and_reports_missing_fields():
    rows = [{"x": 1, "y": 2.5, "z": 0}, {"x": 3, "y": 4.5, "z": 1}]
    matrix = from_records(rows, ["y", "x"])
    assert matrix.tolist() == [[2.5, 1.0], [4.5, 3.0]] and matrix.dtype.name == "float64"
    with pytest.raises(ArrayError, match="field"):
        from_records(rows, ["x", "w"])
    with pytest.raises(ArrayError):
        from_records([], ["x"])


def test_describe_product_and_sign():
    stats = describe([2.0, -3.0, 4.0])
    assert stats["product"] == -24.0 and stats["all_positive"] is False
    assert describe([0.5, 0.5])["product"] == 0.25


def test_summary_text_uses_plain_numbers():
    assert summary_text([1.0, 2.0, 3.0]) == "n=3 mean=2.0 std=0.816 range=[1.0, 3.0]"
    assert summary_text([5]) == "n=1 mean=5.0 std=0.0 range=[5.0, 5.0]"


def test_fill_missing_and_has_missing():
    data = as_array([1.0, float("nan"), 3.0])
    assert has_missing(data) is True
    filled = fill_missing(data, 0.0)
    assert filled.tolist() == [1.0, 0.0, 3.0]
    assert has_missing(filled) is False
    assert has_missing(fill_missing(data)) is True
    assert data.tolist()[0] == 1.0 and data.tolist()[2] == 3.0


def test_running_product():
    assert running_product([1, 2, 3, 4]).tolist() == [1.0, 2.0, 6.0, 24.0]
