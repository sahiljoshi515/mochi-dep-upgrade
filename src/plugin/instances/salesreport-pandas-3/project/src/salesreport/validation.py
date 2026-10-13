"""Checking an export before it is used."""

from typing import List

import pandas as pd

from salesreport.loading import COLUMNS


def check_export(frame: pd.DataFrame) -> List[str]:
    """Every problem with an export, in plain words; [] when it is fine."""
    problems = [f"missing column {column}" for column in COLUMNS if column not in frame.columns]
    if problems:
        return problems
    if frame.empty:
        return ["the export is empty"]
    if (frame["units"] <= 0).any():
        problems.append("units must be positive")
    if (frame["unit_price"].dropna() < 0).any():
        problems.append("unit prices must not be negative")
    if frame["date"].isna().any():
        problems.append("every row needs a date")
    duplicates = int(frame.duplicated(subset=["date", "region", "product"]).sum())
    if duplicates:
        problems.append(f"{duplicates} duplicated order(s)")
    return problems


def drop_bad_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy without the rows that have no date or no positive unit count."""
    keep = frame["date"].notna() & (frame["units"] > 0)
    return frame[keep].reset_index(drop=True)


def require_valid(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame itself, or a ValueError naming every problem."""
    problems = check_export(frame)
    if problems:
        raise ValueError("; ".join(problems))
    return frame
