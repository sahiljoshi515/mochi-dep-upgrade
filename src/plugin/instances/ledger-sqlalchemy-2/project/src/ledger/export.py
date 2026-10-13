"""The journal as CSV text."""

import csv
import io

from sqlalchemy import select

from ledger.models import Account, Entry
from ledger.repository import Ledger

COLUMNS = ("id", "code", "posted", "memo", "category", "cents")


def to_csv(ledger: Ledger) -> str:
    """Every entry with its account code, oldest id first, as CSV with a header."""
    stmt = (
        select([Entry.id, Account.code, Entry.posted, Entry.memo, Entry.category, Entry.cents])
        .select_from(Entry.__table__.join(Account.__table__))
        .order_by(Entry.id)
    )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    with ledger.engine.connect() as connection:
        for row in connection.execute(stmt):
            writer.writerow([row["id"], row["code"], row["posted"].isoformat(), row["memo"], row["category"], row["cents"]])
    return out.getvalue()


def account_codes_csv(ledger: Ledger) -> str:
    """One line per account: code,name,kind."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    with ledger.engine.connect() as connection:
        for row in connection.execute(select([Account.code, Account.name, Account.kind]).order_by(Account.code)):
            writer.writerow([row["code"], row["name"], row["kind"]])
    return out.getvalue()
