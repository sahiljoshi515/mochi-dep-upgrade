from datetime import date

import pytest

from ledger import Ledger, category_breakdown, column_names, create_schema, make_engine, monthly_totals, reflect_table, table_names, to_csv
from ledger.export import account_codes_csv
from ledger.schema import drop_schema


@pytest.fixture
def ledger():
    book = Ledger("sqlite://")
    cash = book.add_account("cash", "Cash", "asset")
    book.add_account("sales", "Sales", "income")
    book.post(cash, date(2026, 1, 15), 1_000, memo="jan a", category="sales")
    book.post(cash, date(2026, 1, 20), -200, memo="jan b", category="fees")
    book.post(cash, date(2026, 2, 3), 700, memo="feb", category="sales")
    book.post(cash, date(2026, 4, 1), -50, memo="apr", category="fees")
    yield book
    book.close()


def test_monthly_totals_are_oldest_first(ledger):
    cash = ledger.find_account("cash").id
    totals = monthly_totals(ledger, cash)
    assert totals == {"2026-01": 800, "2026-02": 700, "2026-04": -50}
    assert list(totals) == ["2026-01", "2026-02", "2026-04"]
    assert monthly_totals(ledger, 999) == {}


def test_category_breakdown_is_largest_first(ledger):
    cash = ledger.find_account("cash").id
    breakdown = category_breakdown(ledger, cash)
    assert breakdown == {"sales": 1_700, "fees": -250}
    assert list(breakdown) == ["sales", "fees"]


def test_to_csv_has_a_header_and_iso_dates(ledger):
    lines = to_csv(ledger).splitlines()
    assert lines[0] == "id,code,posted,memo,category,cents"
    assert lines[1] == "1,CASH,2026-01-15,jan a,sales,1000"
    assert len(lines) == 5
    assert account_codes_csv(ledger) == "CASH,Cash,asset\nSALES,Sales,income\n"


def test_schema_helpers_reflect_the_tables(ledger):
    engine = ledger.engine
    assert table_names(engine) == ["accounts", "entries"]
    assert column_names(engine, "entries") == ["id", "account_id", "posted", "memo", "cents", "category"]
    table = reflect_table(engine, "accounts")
    assert table.name == "accounts" and table.c.code.nullable is False and table.c.code.type.length == 16
    fresh = make_engine("sqlite://")
    assert table_names(fresh) == []
    assert create_schema(fresh) == ["accounts", "entries"]
    drop_schema(fresh)
    assert table_names(fresh) == []
