"""Metrics over a cleaned export."""

import pandas as pd


def monthly_revenue(frame: pd.DataFrame) -> pd.Series:
    """Revenue per calendar month, indexed by month end."""
    return frame.set_index("date")["revenue"].resample("M").sum()


def top_products(frame: pd.DataFrame, n: int = 3) -> pd.Series:
    """The ``n`` products with the most orders, most first."""
    return pd.value_counts(frame["product"]).head(n)


def first_week(frame: pd.DataFrame) -> pd.DataFrame:
    """The orders of the first seven days, indexed by date."""
    return frame.set_index("date").sort_index().first("7D")


def regional_share(frame: pd.DataFrame) -> pd.Series:
    """Each region's share of total revenue, indexed by region."""

    def summarize(group: pd.DataFrame) -> pd.Series:
        label = group["region"].iloc[0]
        return pd.Series({"label": label, "revenue": float(group["revenue"].sum())})

    totals = frame.groupby("region").apply(summarize)
    shares = totals["revenue"] / totals["revenue"].sum()
    shares.index = totals["label"].tolist()
    return shares.astype(float)


def average_order(frame: pd.DataFrame) -> float:
    return float(frame["revenue"].mean())


def units_by_product(frame: pd.DataFrame) -> pd.Series:
    """Units per product, most first."""
    return frame.groupby("product")["units"].sum().sort_values(ascending=False)
