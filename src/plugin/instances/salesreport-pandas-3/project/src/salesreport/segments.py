"""Picking rows out of an export."""

import pandas as pd


def flag_large_orders(frame: pd.DataFrame, threshold: float = 1000.0) -> pd.DataFrame:
    """A copy with a boolean ``large`` column: revenue above ``threshold``."""
    frame = frame.copy()
    frame["large"] = False
    frame["large"][frame["revenue"] > threshold] = True
    return frame


def select_region(frame: pd.DataFrame, region: str) -> pd.DataFrame:
    """One region's rows; changing the result never changes the export."""
    return frame[frame["region"] == region]


def rush_orders(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows whose notes mention a rush, in any case."""
    return frame[frame["notes"].str.contains("rush", case=False, na=False)]
