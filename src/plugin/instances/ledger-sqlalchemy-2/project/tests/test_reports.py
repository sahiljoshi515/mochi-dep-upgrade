from datetime import date

import pytest

from ledger import Ledger, largest_entries, trial_balance
from ledger.reports import balance_check


@pytest.fixture
def ledger():
    book = Ledger("sqlite://")
    cash = book.add_account("cash", "Cash", "asset")
    sales = book.add_account("sales", "Sales", "income")
    book.add_account("loan", "Bank loan", "liability")
    book.post(cash, date(2026, 3, 1), 1_200, memo="sale 1")
    book.post(sales, date(2026, 3, 1), -1_200, memo="sale 1")
    book.post(cash, date(2026, 3, 9), 300, memo="sale 2")
    book.post(sales, date(2026, 3, 9), -300, memo="sale 2")
    yield book
    book.close()


def test_trial_balance_includes_accounts_without_entries(ledger):
    assert trial_balance(ledger) == [
        {"code": "CASH", "name": "Cash", "kind": "asset", "cents": 1_500},
        {"code": "LOAN", "name": "Bank loan", "kind": "liability", "cents": 0},
        {"code": "SALES", "name": "Sales", "kind": "income", "cents": -1_500},
    ]


def test_largest_entries_and_balance_check(ledger):
    top = largest_entries(ledger, limit=2)
    assert [(row["code"], row["cents"]) for row in top] == [("CASH", 1_200), ("SALES", -1_200)]
    assert top[0]["posted"] == date(2026, 3, 1)
    assert balance_check(ledger) is True
