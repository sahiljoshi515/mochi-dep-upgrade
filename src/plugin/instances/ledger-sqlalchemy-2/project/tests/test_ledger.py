from datetime import date

import pytest

from ledger import KINDS, Ledger
from ledger.repository import LedgerError


@pytest.fixture
def ledger():
    book = Ledger("sqlite://")
    yield book
    book.close()


def test_add_and_find_accounts(ledger):
    cash = ledger.add_account(" cash ", " Cash on hand ", "asset")
    ledger.add_account("sales", "Sales", "income")
    assert ledger.find_account("CASH").id == cash
    assert ledger.find_account("cash").name == "Cash on hand"
    assert ledger.find_account("nope") is None
    assert [account.code for account in ledger.accounts()] == ["CASH", "SALES"]
    assert ledger.accounts()[1].kind == "income"


def test_unknown_kind_is_rejected(ledger):
    assert KINDS == ("asset", "liability", "income", "expense")
    with pytest.raises(LedgerError):
        ledger.add_account("eq", "Equity", "equity")


def test_post_and_balance(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    ledger.post(cash, date(2026, 1, 5), 10_000, memo=" opening ")
    ledger.post(cash, date(2026, 1, 2), -2_500, memo="rent", category="rent")
    assert ledger.balance(cash) == 7_500
    assert [entry.memo for entry in ledger.entries(cash)] == ["rent", "opening"]
    assert ledger.entries(cash)[0].category == "rent"
    assert ledger.entry_count() == 2


def test_posting_to_an_unknown_account_or_nothing_fails(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    with pytest.raises(LedgerError):
        ledger.post(999, date(2026, 1, 1), 100)
    with pytest.raises(LedgerError):
        ledger.post(cash, date(2026, 1, 1), 0)
    assert ledger.entry_count() == 0


def test_balance_of_an_empty_account_is_zero(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    assert ledger.balance(cash) == 0
    assert ledger.entries(cash) == []


def test_totals_by_kind_lists_every_kind(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    sales = ledger.add_account("sales", "Sales", "income")
    ledger.add_account("loan", "Bank loan", "liability")
    ledger.post(cash, date(2026, 2, 1), 500)
    ledger.post(sales, date(2026, 2, 1), -500)
    assert ledger.totals_by_kind() == {"asset": 500, "liability": 0, "income": -500, "expense": 0}
