import json
from decimal import Decimal

from invoicer import invoice_from_dict, invoice_from_json, invoice_schema, invoice_to_json, to_record
from invoicer.serialization import items_as_dicts

PAYLOAD = {
    "number": "INV-2026-0003",
    "customer": {"name": "Linus", "email": "linus@example.com", "vat_id": "FI12345678"},
    "issued": "2026-05-01",
    "due": "2026-05-15",
    "currency": "EUR",
    "items": [{"sku": "KRN-001", "description": "Kernel", "quantity": 1, "unit_price": "0.00"}],
    "notes": "Thanks",
}


def test_json_round_trip():
    invoice = invoice_from_dict(PAYLOAD)
    text = invoice_to_json(invoice)
    assert json.loads(text)["number"] == "INV-2026-0003"
    assert invoice_from_json(text) == invoice


def test_dict_round_trip_and_record():
    invoice = invoice_from_dict(PAYLOAD)
    record = to_record(invoice)
    assert record["customer_name"] == "Linus"
    assert "notes" not in record and "customer" not in record
    assert record["subtotal"] == Decimal("0.00")


def test_schema_describes_the_number():
    schema = invoice_schema()
    assert "number" in schema["properties"]
    assert "items" in schema["required"]


def test_items_as_dicts_are_plain():
    rows = items_as_dicts(invoice_from_dict(PAYLOAD))
    assert rows == [{"sku": "KRN-001", "description": "Kernel", "quantity": 1, "unit_price": "0.00", "discount_pct": "0"}]
