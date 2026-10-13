"""The Ledger: one database, its accounts and entries, and the questions asked most often."""

from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import case, func, select

from ledger.db import make_engine, make_session_factory
from ledger.models import DEBIT_KINDS, KINDS, Account, Base, Entry


class LedgerError(ValueError):
    """A bad account kind, an unknown account, a zero entry."""


class Ledger:
    def __init__(self, url: str = "sqlite://") -> None:
        self.engine = make_engine(url)
        Base.metadata.create_all(self.engine)
        self.Session = make_session_factory(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    # ----- accounts -----

    def add_account(self, code: str, name: str, kind: str) -> int:
        if kind not in KINDS:
            raise LedgerError(f"unknown account kind {kind!r}; use one of {', '.join(KINDS)}")
        with self.Session() as session:
            account = Account(code=code.strip().upper(), name=name.strip(), kind=kind)
            session.add(account)
            session.commit()
            return account.id

    def get_account(self, account_id: int) -> Optional[Account]:
        with self.Session() as session:
            return session.query(Account).get(account_id)

    def find_account(self, code: str) -> Optional[Account]:
        with self.Session() as session:
            return session.query(Account).filter_by(code=code.strip().upper()).first()

    def accounts(self) -> List[Account]:
        with self.Session() as session:
            return session.query(Account).order_by(Account.code).all()

    # ----- entries -----

    def post(self, account_id: int, posted: date, cents: int, memo: str = "", category: str = "general") -> int:
        if cents == 0:
            raise LedgerError("an entry must move money")
        with self.Session() as session:
            if session.query(Account).get(account_id) is None:
                raise LedgerError(f"no account {account_id}")
            entry = Entry(account_id=account_id, posted=posted, cents=cents, memo=memo.strip(), category=category)
            session.add(entry)
            session.commit()
            return entry.id

    def entries(self, account_id: int) -> List[Entry]:
        with self.Session() as session:
            return session.query(Entry).filter(Entry.account_id == account_id).order_by(Entry.posted, Entry.id).all()

    def balance(self, account_id: int) -> int:
        """The account's balance in cents: the sum of its entries, 0 without any."""
        with self.Session() as session:
            stmt = select([func.coalesce(func.sum(Entry.cents), 0)]).where(Entry.account_id == account_id)
            return int(session.execute(stmt).scalar())

    def totals_by_kind(self) -> Dict[str, int]:
        """Raw totals per account kind, every kind present (0 without entries)."""
        with self.Session() as session:
            stmt = (
                select([Account.kind, func.coalesce(func.sum(Entry.cents), 0).label("cents")])
                .select_from(Account.__table__.outerjoin(Entry.__table__))
                .group_by(Account.kind)
            )
            found = {row["kind"]: int(row["cents"]) for row in session.execute(stmt).fetchall()}
        return {kind: found.get(kind, 0) for kind in KINDS}

    def signed_totals(self) -> Dict[str, int]:
        """Totals per kind as a reader expects them: debit-normal kinds as they are, the others
        with the sign flipped, so a liability with credits shows a positive amount."""
        with self.Session() as session:
            sign = case([(Account.kind.in_(DEBIT_KINDS), 1)], else_=-1)
            stmt = (
                select([Account.kind, func.coalesce(func.sum(Entry.cents * sign), 0).label("cents")])
                .select_from(Account.__table__.join(Entry.__table__))
                .group_by(Account.kind)
            )
            found = {row["kind"]: int(row["cents"]) for row in session.execute(stmt)}
        return {kind: found.get(kind, 0) for kind in KINDS}

    def entry_count(self) -> int:
        with self.Session() as session:
            return int(session.execute(select([func.count(Entry.id)])).scalar())
