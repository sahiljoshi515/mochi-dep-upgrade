from datetime import date
from decimal import Decimal

from invoicer import Customer, Invoice, LineItem, invoice_from_dict, validate_payload

PAYLOAD = {
    "number": "INV-2026-0001",
    "customer": {"name": "Ada Lovelace", "email": "ada@example.com", "country": "gb"},
    "issued": "2026-03-01",
    "due": "2026-03-31",
    "currency": "usd",
    "items": [
        {"sku": "abc-001", "description": "Widget", "quantity": 3, "unit_price": "19.99"},
        {"sku": "ABC-002", "description": "Gadget", "quantity": 1, "unit_price": "100.00", "discount_pct": "10"},
    ],
}


def test_customer_is_normalized():
    customer = Customer(name="  Ada ", email="ADA@Example.com", country="gb")
    assert customer.name == "Ada"
    assert customer.email == "ada@example.com"
    assert customer.country == "GB"
    assert customer.vat_id is None


def test_line_item_amounts():
    item = LineItem(sku=" abc-001 ", description="Widget", quantity=3, unit_price="19.99", discount_pct="10")
    assert item.sku == "ABC-001"
    assert item.gross == Decimal("59.97")
    assert item.net == Decimal("53.97")


def test_invoice_subtotal_and_item_count():
    invoice = invoice_from_dict(PAYLOAD)
    assert invoice.currency == "USD"
    assert invoice.issued == date(2026, 3, 1)
    assert invoice.item_count == 4
    assert invoice.subtotal == Decimal("149.97")


def test_unknown_currency_is_rejected():
    problems = validate_payload({**PAYLOAD, "currency": "XXX"})
    assert [problem.field for problem in problems] == ["currency"]
    assert "XXX" in problems[0].message


def test_due_before_issued_is_rejected():
    problems = validate_payload({**PAYLOAD, "due": "2026-02-01"})
    assert len(problems) == 1
    assert "before" in problems[0].message


def test_unknown_fields_are_rejected():
    problems = validate_payload({**PAYLOAD, "paid": True})
    assert problems and problems[0].field == "paid"


def test_bad_sku_and_quantity_are_reported_by_location():
    bad = {**PAYLOAD, "items": [{"sku": "nope", "description": "x", "quantity": 0, "unit_price": "1.00"}]}
    fields = {problem.field for problem in validate_payload(bad)}
    assert fields == {"items.0.sku", "items.0.quantity"}


def test_with_reference_returns_a_new_invoice():
    invoice = invoice_from_dict(PAYLOAD)
    tagged = invoice.with_reference(" PO-77 ")
    assert tagged.reference == "PO-77"
    assert invoice.reference is None
    assert isinstance(tagged, Invoice)
