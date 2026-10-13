"""Cleaning an export: prices carried forward, notes filled, text normalized."""

import pandas as pd


def fill_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Carry the last known unit price forward into missing ones and recompute revenue."""
    frame = frame.copy()
    frame["unit_price"] = frame["unit_price"].fillna(method="ffill")
    frame["revenue"] = frame["units"] * frame["unit_price"]
    return frame


def fill_notes(frame: pd.DataFrame) -> pd.DataFrame:
    """Missing notes become empty strings."""
    frame = frame.copy()
    frame["notes"].fillna("", inplace=True)
    return frame


def normalize_text(frame: pd.DataFrame) -> pd.DataFrame:
    """Strip and title-case every text column."""
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].str.strip().str.title()
    return frame


def round_prices(frame: pd.DataFrame, places: int = 2) -> pd.DataFrame:
    """Every float in the frame rounded to ``places``."""
    return frame.applymap(lambda value: round(value, places) if isinstance(value, float) else value)


def clean(frame: pd.DataFrame) -> pd.DataFrame:
    return normalize_text(fill_notes(fill_prices(frame)))
