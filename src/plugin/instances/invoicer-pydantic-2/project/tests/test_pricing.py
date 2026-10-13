from decimal import Decimal

import pytest

from invoicer import InvoiceError, apply_discount, invoice_from_dict, line_totals, load_settings, subtotal, tax, total
from invoicer.pricing import late_fee, split_by_sku

PAYLOAD = {
    "number": "INV-2026-0002",
    "customer": {"name": "Grace Hopper", "email": "grace@example.com"},
    "issued": "2026-04-01",
    "due": "2026-04-30",
    "items": [
        {"sku": "NAV-100", "description": "Compass", "quantity": 2, "unit_price": "25.00"},
        {"sku": "NAV-100", "description": "Compass, spare", "quantity": 1, "unit_price": "25.00"},
        {"sku": "NAV-200", "description": "Chart", "quantity": 4, "unit_price": "12.50"},
    ],
}


def test_totals_with_explicit_settings():
    invoice = invoice_from_dict(PAYLOAD)
    settings = load_settings(tax_rate="0.1")
    assert subtotal(invoice) == Decimal("125.00")
    assert tax(invoice, settings) == Decimal("12.50")
    assert total(invoice, settings) == Decimal("137.50")


def test_line_totals_carry_gross_and_net():
    rows = line_totals(invoice_from_dict(PAYLOAD))
    assert [row["sku"] for row in rows] == ["NAV-100", "NAV-100", "NAV-200"]
    assert rows[2]["gross"] == Decimal("50.00")
    assert rows[2]["net"] == Decimal("50.00")
    assert rows[2]["discount_pct"] == Decimal("0")


def test_apply_discount_makes_a_new_invoice():
    invoice = invoice_from_dict(PAYLOAD)
    cheaper = apply_discount(invoice, Decimal("20"))
    assert subtotal(cheaper) == Decimal("100.00")
    assert subtotal(invoice) == Decimal("125.00")
    assert all(item.discount_pct == Decimal("20") for item in cheaper.items)


def test_discount_out_of_range_is_an_invoice_error():
    with pytest.raises(InvoiceError):
        apply_discount(invoice_from_dict(PAYLOAD), Decimal("120"))


def test_late_fee_and_split():
    invoice = invoice_from_dict(PAYLOAD)
    settings = load_settings(tax_rate="0", late_fee_pct="2")
    assert late_fee(invoice, settings, days_late=0) == Decimal("0.00")
    assert late_fee(invoice, settings, days_late=3) == Decimal("2.50")
    assert split_by_sku(invoice) == {"NAV-100": Decimal("75.00"), "NAV-200": Decimal("50.00")}
