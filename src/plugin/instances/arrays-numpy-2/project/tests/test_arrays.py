import pytest

from arrays import ArrayError, bin_labels, bounding_box, centroid, column, count_in_bins, describe, histogram, moving_average, parse_matrix, polygon_area, quantiles, to_csv_lines, zscore

MATRIX = "1 2 3\n4 5 6\n7 8 10\n"


def test_parse_matrix_and_column():
    matrix = parse_matrix(MATRIX)
    assert matrix.shape == (3, 3)
    assert column(matrix, 2).tolist() == [3.0, 6.0, 10.0]
    with pytest.raises(ArrayError):
        parse_matrix("1 2\n3\n")
    with pytest.raises(ArrayError):
        column(column(matrix, 0), 0)


def test_describe_and_zscore():
    stats = describe([1.0, 2.0, 3.0])
    assert stats["count"] == 3 and stats["mean"] == 2.0 and stats["min"] == 1.0 and stats["max"] == 3.0
    assert round(stats["std"], 3) == 0.816
    assert stats["product"] == 6.0 and stats["all_positive"] is True
    assert zscore([2.0, 2.0, 2.0]).tolist() == [0.0, 0.0, 0.0]
    assert [round(value, 3) for value in zscore([1.0, 2.0, 3.0]).tolist()] == [-1.225, 0.0, 1.225]
    with pytest.raises(ArrayError):
        describe([])


def test_moving_average():
    assert moving_average([1.0, 2.0, 3.0, 4.0], 2).tolist() == [1.5, 2.5, 3.5]
    with pytest.raises(ArrayError):
        moving_average([1.0], 2)


def test_histogram_bins_and_quantiles():
    counts, edges = histogram([1, 2, 2, 3, 9], bins=2)
    assert counts == [4, 1] and edges == [1.0, 5.0, 9.0]
    assert bin_labels([0, 1, 5, 9, 10], [1.0, 5.0, 9.0]).tolist() == [0, 1, 2, 3, 3]
    assert count_in_bins([0, 1, 5, 9, 10], [1.0, 5.0, 9.0]) == [1, 1, 1, 2]
    assert quantiles([1, 2, 3, 4]) == [1.75, 2.5, 3.25]


def test_geometry():
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    assert polygon_area(square) == 4.0
    low, high = bounding_box(square)
    assert low.tolist() == [0.0, 0.0] and high.tolist() == [2.0, 2.0]
    assert centroid(square).tolist() == [1.0, 1.0]
    with pytest.raises(ArrayError):
        polygon_area([[0, 0], [1, 1]])


def test_csv_lines():
    assert to_csv_lines(parse_matrix(MATRIX), header=["a", "b", "c"]) == ["a,b,c", "1,2,3", "4,5,6", "7,8,10"]
    assert to_csv_lines([1.23456, 2.5]) == ["1.235,2.5"]
