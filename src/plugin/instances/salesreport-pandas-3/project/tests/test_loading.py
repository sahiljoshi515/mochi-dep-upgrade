import pytest

from salesreport import load_sales, round_prices, to_records

SALES = """date region product units unit_price notes
2026-01-03 west widget 10 2.50 -
2026-01-05 east gadget 3 100.00 rush
2026-01-20 west gadget 2 - -
2026-02-02 north widget 40 2.50 bulk
2026-02-15 east gizmo 5 20.00 -
2026-03-01 west widget 1 2.499 -
2026-03-09 north widget 4 2.50 -
"""


def test_load_sales_parses_dates_missing_values_and_revenue():
    frame = load_sales(SALES)
    assert list(frame.columns) == ["date", "region", "product", "units", "unit_price", "notes", "revenue"]
    assert str(frame["date"].dtype).startswith("datetime64")
    assert frame["revenue"].tolist()[0] == 25.0
    assert frame["unit_price"].isna().tolist() == [False, False, True, False, False, False, False]
    assert frame["revenue"].isna().tolist()[2] is True
    assert frame["notes"].isna().sum() == 5


def test_load_sales_requires_every_column():
    with pytest.raises(ValueError, match="unit_price"):
        load_sales("date region product units notes\n2026-01-01 west widget 1 -\n")


def test_round_prices_rounds_floats_only():
    rounded = round_prices(load_sales(SALES))
    assert rounded["unit_price"].tolist()[5] == 2.5
    assert rounded["units"].tolist()[5] == 1
    assert rounded["region"].tolist()[0] == "west"


def test_to_records_uses_iso_dates_and_none():
    records = to_records(load_sales(SALES))
    assert records[0]["date"] == "2026-01-03"
    assert records[0]["notes"] is None
    assert records[2]["unit_price"] is None
    assert records[1]["notes"] == "rush"
