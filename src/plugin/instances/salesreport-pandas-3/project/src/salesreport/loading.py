"""Reading the warehouse exports."""

import io
from typing import List

import pandas as pd

COLUMNS: List[str] = ["date", "region", "product", "units", "unit_price", "notes"]


def load_sales(text: str) -> pd.DataFrame:
    """Rows of ``date region product units unit_price notes`` separated by whitespace, with a
    header; ``-`` marks a missing value. Adds ``revenue`` (units times unit price)."""
    frame = pd.read_csv(
        io.StringIO(text),
        delim_whitespace=True,
        parse_dates=["date"],
        infer_datetime_format=True,
        na_values=["-"],
    )
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"the export lacks the columns {', '.join(missing)}")
    frame["revenue"] = frame["units"] * frame["unit_price"]
    return frame


def load_prices(text: str) -> pd.Series:
    """A ``date,price`` CSV as a Series of prices indexed by date, oldest first."""
    frame = pd.read_csv(io.StringIO(text), parse_dates=["date"], index_col="date", infer_datetime_format=True)
    return frame["price"].sort_index()
