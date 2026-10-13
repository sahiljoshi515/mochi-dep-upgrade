from salesreport import clean, flag_large_orders, load_prices, load_sales, rush_orders, select_region

SALES = """date region product units unit_price notes
2026-01-03  west   widget 10 2.50 -
2026-01-05 east gadget 3 100.00 rush
2026-01-20 west gadget 2 - -
2026-02-02 north widget 40 2.50 bulk
2026-02-15 east gizmo 5 20.00 -
2026-03-01 west widget 1 2.499 -
2026-03-09 north widget 4 2.50 -
"""


def test_clean_fills_prices_and_notes_and_titles_text():
    cleaned = clean(load_sales(SALES))
    assert cleaned["unit_price"].tolist()[2] == 100.0
    assert cleaned["revenue"].tolist()[2] == 200.0
    assert cleaned["notes"].tolist() == ["", "Rush", "", "Bulk", "", "", ""]
    assert cleaned["region"].tolist() == ["West", "East", "West", "North", "East", "West", "North"]
    assert cleaned["product"].tolist()[1] == "Gadget"
    assert cleaned["notes"].isna().sum() == 0


def test_clean_leaves_the_export_alone():
    frame = load_sales(SALES)
    clean(frame)
    assert frame["unit_price"].isna().tolist()[2] is True
    assert frame["region"].tolist()[0] == "west"
    assert frame["notes"].isna().tolist()[0] is True


def test_flag_large_orders_marks_rows_above_the_threshold():
    cleaned = clean(load_sales(SALES))
    flagged = flag_large_orders(cleaned, threshold=150.0)
    assert flagged["large"].tolist() == [False, True, True, False, False, False, False]
    assert flag_large_orders(cleaned)["large"].tolist() == [False] * 7
    assert "large" not in cleaned.columns


def test_select_region_and_rush_orders_are_independent_copies():
    cleaned = clean(load_sales(SALES))
    west = select_region(cleaned, "West")
    assert west["units"].tolist() == [10, 2, 1]
    west["units"] = 0
    assert cleaned["units"].tolist()[0] == 10
    rush = rush_orders(cleaned)
    assert rush["product"].tolist() == ["Gadget"]
    assert rush_orders(load_sales(SALES))["units"].tolist() == [3]


def test_load_prices_sorts_by_date():
    prices = load_prices("date,price\n2026-01-02,3.5\n2026-01-01,3.0\n2026-01-03,4.25\n")
    assert prices.tolist() == [3.0, 3.5, 4.25]
    assert [stamp.strftime("%Y-%m-%d") for stamp in prices.index] == ["2026-01-01", "2026-01-02", "2026-01-03"]
