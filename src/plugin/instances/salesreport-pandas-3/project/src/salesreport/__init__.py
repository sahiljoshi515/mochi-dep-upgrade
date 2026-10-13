"""salesreport: sales reports on pandas."""

from salesreport.cleaning import clean, fill_notes, fill_prices, normalize_text, round_prices
from salesreport.formatting import format_money, format_series, format_table
from salesreport.loading import COLUMNS, load_prices, load_sales
from salesreport.metrics import average_order, first_week, monthly_revenue, regional_share, top_products, units_by_product
from salesreport.reporting import pivot, region_table, summary, to_records
from salesreport.segments import flag_large_orders, rush_orders, select_region

__all__ = [
    "COLUMNS",
    "average_order",
    "clean",
    "fill_notes",
    "fill_prices",
    "first_week",
    "flag_large_orders",
    "format_money",
    "format_series",
    "format_table",
    "load_prices",
    "load_sales",
    "monthly_revenue",
    "normalize_text",
    "pivot",
    "region_table",
    "regional_share",
    "round_prices",
    "rush_orders",
    "select_region",
    "summary",
    "to_records",
    "top_products",
    "units_by_product",
]
