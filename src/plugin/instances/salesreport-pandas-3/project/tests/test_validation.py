import pytest

from salesreport import load_sales
from salesreport.validation import check_export, drop_bad_rows, require_valid

SALES = """date region product units unit_price notes
2026-01-03 west widget 10 2.50 -
2026-01-05 east gadget 0 100.00 rush
2026-01-05 east gadget 3 -1.00 -
2026-01-05 east gadget 2 5.00 dup
"""


def test_check_export_names_every_problem():
    frame = load_sales(SALES)
    assert check_export(frame) == ["units must be positive", "unit prices must not be negative", "2 duplicated order(s)"]
    assert check_export(frame.drop(columns=["notes"])) == ["missing column notes"]
    assert check_export(frame.iloc[0:0]) == ["the export is empty"]


def test_drop_bad_rows_and_require_valid():
    frame = load_sales(SALES)
    kept = drop_bad_rows(frame)
    assert kept["units"].tolist() == [10, 3, 2]
    assert len(frame) == 4
    with pytest.raises(ValueError, match="units must be positive"):
        require_valid(frame)
    clean = load_sales("date region product units unit_price notes\n2026-01-03 west widget 10 2.50 -\n")
    assert require_valid(clean) is clean
