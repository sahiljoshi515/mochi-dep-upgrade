"""Tables and records for the monthly report."""

from typing import List

import pandas as pd


def pivot(frame: pd.DataFrame) -> pd.DataFrame:
    """Revenue by region (rows) and product (columns), 0 where nothing sold."""
    return pd.pivot_table(frame, index="region", columns="product", values="revenue", aggfunc="sum", fill_value=0.0)


def region_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Units and revenue per region."""
    return frame.groupby("region").agg(units=("units", "sum"), revenue=("revenue", "sum")).reset_index()


def to_records(frame: pd.DataFrame) -> List[dict]:
    """Plain records: dates as ISO strings, missing values as None."""
    records = []
    for record in frame.to_dict("records"):
        record["date"] = record["date"].strftime("%Y-%m-%d")
        for key, value in list(record.items()):
            if isinstance(value, float) and value != value:
                record[key] = None
        records.append(record)
    return records


def summary(frame: pd.DataFrame) -> dict:
    return {
        "orders": int(len(frame)),
        "units": int(frame["units"].sum()),
        "revenue": float(frame["revenue"].sum()),
        "regions": sorted(frame["region"].unique().tolist()),
        "start": frame["date"].min().strftime("%Y-%m-%d"),
        "end": frame["date"].max().strftime("%Y-%m-%d"),
    }
