from salesreport import clean, first_week, format_table, load_sales, monthly_revenue, regional_share, top_products

SALES = """date region product units unit_price notes
2026-01-03 west widget 10 2.50 -
2026-01-05 east gadget 3 100.00 rush
2026-01-20 west gadget 2 - -
2026-02-02 north widget 40 2.50 bulk
2026-02-15 east gizmo 5 20.00 -
2026-03-01 west widget 1 2.499 -
2026-03-09 north widget 4 2.50 -
"""


def cleaned():
    return clean(load_sales(SALES))


def test_top_products_counts_orders():
    top = top_products(cleaned(), 2)
    assert top.to_dict() == {"Widget": 4, "Gadget": 2}
    assert top_products(cleaned()).tolist() == [4, 2, 1]


def test_first_week_keeps_seven_days_from_the_first_order():
    week = first_week(cleaned())
    assert week["product"].tolist() == ["Widget", "Gadget"]
    assert [stamp.strftime("%Y-%m-%d") for stamp in week.index] == ["2026-01-03", "2026-01-05"]
    assert "date" not in week.columns


def test_regional_share_sums_to_one():
    shares = regional_share(cleaned())
    assert shares.index.tolist() == ["East", "North", "West"]
    assert [round(value, 4) for value in shares.tolist()] == [0.5424, 0.1492, 0.3085]
    assert round(shares.sum(), 6) == 1.0


def test_monthly_revenue_is_indexed_by_month_end():
    monthly = monthly_revenue(cleaned())
    assert [stamp.strftime("%Y-%m-%d") for stamp in monthly.index] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert [round(value, 3) for value in monthly.tolist()] == [525.0, 200.0, 12.499]


def test_format_table_shows_money_and_no_index():
    text = format_table(cleaned()[["region", "units", "revenue"]].head(2))
    lines = text.splitlines()
    assert lines[0].split() == ["region", "units", "revenue"]
    assert lines[1].split() == ["West", "10", "25.00"]
    assert lines[2].split() == ["East", "3", "300.00"]
