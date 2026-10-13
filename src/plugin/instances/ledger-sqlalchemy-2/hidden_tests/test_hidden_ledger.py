from datetime import date

import pytest

from ledger import Ledger, import_csv_text, import_rows
from ledger.repository import LedgerError


@pytest.fixture
def ledger():
    book = Ledger("sqlite://")
    yield book
    book.close()


def test_get_account_by_id_and_missing(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    found = ledger.get_account(cash)
    assert found is not None and found.code == "CASH" and found.kind == "asset"
    assert ledger.get_account(cash + 1) is None


def test_signed_totals_flip_credit_normal_kinds(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    sales = ledger.add_account("sales", "Sales", "income")
    loan = ledger.add_account("loan", "Loan", "liability")
    rent = ledger.add_account("rent", "Rent", "expense")
    ledger.post(cash, date(2026, 1, 1), 500)
    ledger.post(sales, date(2026, 1, 1), -500)
    ledger.post(cash, date(2026, 1, 2), 300)
    ledger.post(loan, date(2026, 1, 2), -300)
    ledger.post(rent, date(2026, 1, 3), 100)
    ledger.post(cash, date(2026, 1, 3), -100)
    assert ledger.signed_totals() == {"asset": 700, "liability": 300, "income": 500, "expense": 100}
    assert ledger.totals_by_kind() == {"asset": 700, "liability": -300, "income": -500, "expense": 100}


def test_import_rows_commits_and_counts(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    rows = [
        {"account_id": cash, "posted": "2026-01-03", "cents": "250", "memo": " three "},
        {"account_id": cash, "posted": date(2026, 1, 1), "cents": 100, "memo": "one", "category": "sales"},
        {"account_id": cash, "posted": "2026-01-02", "cents": -50},
    ]
    assert import_rows(ledger, rows) == 3
    assert ledger.balance(cash) == 300
    entries = ledger.entries(cash)
    assert [(entry.memo, entry.category, entry.cents) for entry in entries] == [("one", "sales", 100), ("", "general", -50), ("three", "general", 250)]
    assert ledger.entry_count() == 3
    assert import_rows(ledger, []) == 0


def test_import_csv_text_parses_and_validates(ledger):
    cash = ledger.add_account("cash", "Cash", "asset")
    text = "account_id,posted,cents,memo,category\n" f"{cash},2026-02-01,1000,deposit,\n" f"{cash},2026-02-02,-400,,fees\n"
    assert import_csv_text(ledger, text) == 2
    assert ledger.balance(cash) == 600
    assert [entry.category for entry in ledger.entries(cash)] == ["general", "fees"]
    with pytest.raises(LedgerError):
        import_csv_text(ledger, "account_id,posted\n1,2026-01-01\n")
    with pytest.raises(LedgerError):
        import_rows(ledger, [{"account_id": cash, "posted": "2026-01-01", "cents": 0}])
    assert ledger.entry_count() == 2
