from salesreport import average_order, fill_prices, format_money, format_series, load_sales, monthly_revenue, pivot, region_table, summary, units_by_product

SALES = """date region product units unit_price notes
2026-01-03 west widget 10 2.50 -
2026-01-05 east gadget 3 100.00 rush
2026-01-20 west gadget 2 - -
2026-02-02 north widget 40 2.50 bulk
2026-02-15 east gizmo 5 20.00 -
2026-03-01 west widget 1 2.499 -
2026-03-09 north widget 4 2.50 -
"""


def frame():
    return fill_prices(load_sales(SALES))


def test_monthly_revenue_per_month():
    monthly = monthly_revenue(frame())
    assert [round(value, 3) for value in monthly.tolist()] == [525.0, 200.0, 12.499]
    assert len(monthly) == 3


def test_pivot_and_region_table():
    table = pivot(frame())
    assert table.loc["west", "gadget"] == 200.0
    assert table.loc["north", "gizmo"] == 0.0
    regions = region_table(frame())
    assert regions["region"].tolist() == ["east", "north", "west"]
    assert regions["units"].tolist() == [8, 44, 13]


def test_summary_and_averages():
    assert summary(frame()) == {"orders": 7, "units": 65, "revenue": 737.499, "regions": ["east", "north", "west"], "start": "2026-01-03", "end": "2026-03-09"}
    assert round(average_order(frame()), 3) == 105.357
    assert units_by_product(frame()).to_dict() == {"widget": 55, "gadget": 5, "gizmo": 5}


def test_money_formatting():
    assert format_money(1234.5) == "1,234.50"
    assert format_series(monthly_revenue(frame()))[0].endswith(": 525.00")
