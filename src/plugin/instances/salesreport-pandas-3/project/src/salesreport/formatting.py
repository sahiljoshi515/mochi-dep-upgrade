"""Money strings and printable tables."""

from typing import List

import pandas as pd


def format_money(value: float) -> str:
    return f"{value:,.2f}"


def format_table(frame: pd.DataFrame) -> str:
    """The frame as text, every float as money, without the index."""
    shown = frame.applymap(lambda value: format_money(value) if isinstance(value, float) else value)
    return shown.to_string(index=False)


def format_series(series: pd.Series) -> List[str]:
    """``"<index>: <money>"`` per entry."""
    return [f"{index}: {format_money(float(value))}" for index, value in series.items()]
