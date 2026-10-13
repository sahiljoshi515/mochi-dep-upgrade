"""Reports: the trial balance, monthly totals, category breakdowns and the largest entries."""

from typing import Dict, List

from sqlalchemy import func, select

from ledger.models import Account, Entry
from ledger.repository import Ledger

TRIAL_BALANCE_SQL = (
    "SELECT a.code AS code, a.name AS name, a.kind AS kind, COALESCE(SUM(e.cents), 0) AS cents "
    "FROM accounts a LEFT JOIN entries e ON e.account_id = a.id "
    "GROUP BY a.id ORDER BY a.code"
)
MONTHLY_SQL = (
    "SELECT substr(posted, 1, 7) AS month, SUM(cents) AS cents FROM entries "
    "WHERE account_id = :account_id GROUP BY month ORDER BY month"
)


def trial_balance(ledger: Ledger) -> List[dict]:
    """Every account with its balance, by code; accounts without entries show 0."""
    rows = ledger.engine.execute(TRIAL_BALANCE_SQL).fetchall()
    return [{"code": row["code"], "name": row["name"], "kind": row["kind"], "cents": int(row["cents"])} for row in rows]


def monthly_totals(ledger: Ledger, account_id: int) -> Dict[str, int]:
    """Cents per month (``YYYY-MM``) for one account, oldest first."""
    with ledger.engine.connect() as connection:
        rows = connection.execute(MONTHLY_SQL, {"account_id": account_id})
        return {row["month"]: int(row["cents"]) for row in rows}


def category_breakdown(ledger: Ledger, account_id: int) -> Dict[str, int]:
    """Cents per category for one account, largest first."""
    with ledger.Session() as session:
        stmt = (
            select([Entry.category, func.sum(Entry.cents).label("cents")])
            .where(Entry.account_id == account_id)
            .group_by(Entry.category)
            .order_by(func.sum(Entry.cents).desc(), Entry.category)
        )
        return {row["category"]: int(row["cents"]) for row in session.execute(stmt)}


def largest_entries(ledger: Ledger, limit: int = 5) -> List[dict]:
    """The entries moving the most money, with their account codes."""
    with ledger.Session() as session:
        rows = (
            session.query(Entry.id, Account.code, Entry.posted, Entry.memo, Entry.cents)
            .join(Account, Account.id == Entry.account_id)
            .order_by(func.abs(Entry.cents).desc(), Entry.id)
            .limit(limit)
            .all()
        )
        return [{"id": row.id, "code": row.code, "posted": row.posted, "memo": row.memo, "cents": row.cents} for row in rows]


def balance_check(ledger: Ledger) -> bool:
    """Whether debits and credits cancel out over the whole ledger."""
    with ledger.Session() as session:
        total = session.execute(select([func.coalesce(func.sum(Entry.cents), 0)])).scalar()
    return int(total) == 0
