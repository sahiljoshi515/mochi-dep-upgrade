"""Bulk imports: entries from dicts or CSV text, committed in one transaction."""

import csv
import io
from datetime import date
from typing import Iterable, List

from ledger.models import Entry
from ledger.repository import Ledger, LedgerError

COLUMNS = ("account_id", "posted", "cents", "memo", "category")


def _normalize(row: dict) -> dict:
    posted = row["posted"]
    if isinstance(posted, str):
        posted = date.fromisoformat(posted)
    cents = int(row["cents"])
    if cents == 0:
        raise LedgerError("an imported entry must move money")
    return {
        "account_id": int(row["account_id"]),
        "posted": posted,
        "cents": cents,
        "memo": str(row.get("memo") or "").strip(),
        "category": str(row.get("category") or "general").strip() or "general",
    }


def import_rows(ledger: Ledger, rows: Iterable[dict]) -> int:
    """Insert every row as an entry in one transaction; returns how many were inserted."""
    values: List[dict] = [_normalize(row) for row in rows]
    if not values:
        return 0
    result = ledger.engine.execute(Entry.__table__.insert(), values)
    return int(result.rowcount)


def import_csv_text(ledger: Ledger, text: str) -> int:
    """Rows from CSV text with a header of account_id, posted, cents, memo, category."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [name for name in COLUMNS[:3] if name not in (reader.fieldnames or [])]
    if missing:
        raise LedgerError(f"CSV lacks the columns {', '.join(missing)}")
    return import_rows(ledger, list(reader))
