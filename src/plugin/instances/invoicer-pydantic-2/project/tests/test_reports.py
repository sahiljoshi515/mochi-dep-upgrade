from datetime import date
from decimal import Decimal

from invoicer import invoice_from_dict, load_settings
from invoicer.reports import as_rows, by_currency, customer_totals, overdue, summary_line


def make(number, name, due, currency="USD", price="10.00"):
    return invoice_from_dict(
        {
            "number": number,
            "customer": {"name": name, "email": f"{name.lower()}@example.com"},
            "issued": "2026-01-01",
            "due": due,
            "currency": currency,
            "items": [{"sku": "GEN-001", "description": "Thing", "quantity": 1, "unit_price": price}],
        }
    )


INVOICES = [
    make("INV-2026-0010", "Ada", "2026-01-15"),
    make("INV-2026-0011", "Bob", "2026-02-15", price="20.00"),
    make("INV-2026-0012", "Ada", "2026-03-15", currency="EUR"),
]
SETTINGS = load_settings(tax_rate="0.5")


def test_summary_line():
    assert summary_line(INVOICES[0], SETTINGS) == "INV-2026-0010 Ada: 1 items, 15.00 USD, due 2026-01-15"


def test_customer_totals_are_sorted_by_name():
    assert customer_totals(INVOICES, SETTINGS) == {"Ada": Decimal("30.00"), "Bob": Decimal("30.00")}


def test_overdue_is_oldest_first():
    assert overdue(INVOICES, date(2026, 3, 1)) == ["INV-2026-0010", "INV-2026-0011"]


def test_rows_and_currency_totals():
    rows = as_rows(INVOICES, SETTINGS)
    assert rows[1] == {"number": "INV-2026-0011", "issued": date(2026, 1, 1), "due": date(2026, 2, 15), "currency": "USD", "items": 1, "total": Decimal("30.00")}
    assert by_currency(INVOICES, SETTINGS) == {"USD": Decimal("45.00"), "EUR": Decimal("15.00")}
