"""Accounts and journal entries."""

from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ledger.db import Base

KINDS = ("asset", "liability", "income", "expense")
# Debit-normal kinds carry their totals as they are; the others are shown with the sign flipped.
DEBIT_KINDS = ("asset", "expense")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    code = Column(String(16), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    kind = Column(String(16), nullable=False)

    entries = relationship("Entry", backref="account", cascade="all, delete-orphan", order_by="Entry.id")

    def __repr__(self) -> str:
        return f"Account(code={self.code!r}, name={self.name!r}, kind={self.kind!r})"


class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    posted = Column(Date, nullable=False)
    memo = Column(String(200), nullable=False, default="")
    cents = Column(Integer, nullable=False)
    category = Column(String(32), nullable=False, default="general")

    def __repr__(self) -> str:
        return f"Entry(account_id={self.account_id}, posted={self.posted}, cents={self.cents}, memo={self.memo!r})"
