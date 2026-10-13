import json
from decimal import Decimal

import pytest

from invoicer import Invoice, apply_discount, describe_fields, field_names, invoice_schema, invoice_to_json, validate_payload

PAYLOAD = {
    "number": "INV-2026-0100",
    "customer": {"name": "Ada Lovelace", "email": "ada@example.com", "country": "gb"},
    "issued": "2026-03-01",
    "due": "2026-03-31",
    "items": [
        {"sku": "abc-001", "description": "Widget", "quantity": 3, "unit_price": "19.99"},
        {"sku": "ABC-002", "description": "Gadget", "quantity": 1, "unit_price": "100.00", "discount_pct": "10"},
    ],
}


def test_model_validate_and_model_dump_round_trip():
    invoice = Invoice.model_validate(PAYLOAD)
    assert Invoice.model_validate(invoice.model_dump()) == invoice
    dumped = invoice.model_dump(mode="json")
    assert dumped["issued"] == "2026-03-01"
    assert dumped["items"][0]["unit_price"] == "19.99"
    assert dumped["items"][0]["sku"] == "ABC-001"


def test_json_text_is_sorted_with_iso_dates_and_string_decimals():
    text = invoice_to_json(Invoice.model_validate(PAYLOAD))
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert data["due"] == "2026-03-31"
    assert data["items"][1]["discount_pct"] == "10"
    assert text.index('"customer"') < text.index('"items"') < text.index('"number"')


def test_schema_uses_defs_and_keeps_patterns():
    schema = invoice_schema()
    assert "LineItem" in schema["$defs"] and "Customer" in schema["$defs"]
    assert schema["properties"]["number"]["pattern"] == r"^INV-\d{4}-\d{4}$"
    assert schema["properties"]["kind"]["const"] == "invoice"
    assert schema["properties"]["items"]["minItems"] == 1


def test_frozen_models_raise_validation_error_on_assignment():
    invoice = Invoice.model_validate(PAYLOAD)
    with pytest.raises(Exception) as caught:
        invoice.items[0].quantity = 5
    assert type(caught.value).__name__ == "ValidationError"
    with pytest.raises(Exception) as caught:
        invoice.number = "INV-2026-0101"
    assert type(caught.value).__name__ == "ValidationError"


def test_optional_reference_defaults_to_none_and_kind_is_fixed():
    invoice = Invoice.model_validate(PAYLOAD)
    assert invoice.reference is None
    assert invoice.kind == "invoice"
    assert [problem.field for problem in validate_payload({**PAYLOAD, "kind": "receipt"})] == ["kind"]


def test_apply_discount_copies_without_touching_the_original():
    invoice = Invoice.model_validate(PAYLOAD)
    cheaper = apply_discount(invoice, Decimal("50"))
    assert cheaper.subtotal == Decimal("79.98")
    assert invoice.subtotal == Decimal("149.97")
    assert cheaper.model_dump()["items"][0]["discount_pct"] == Decimal("50")


def test_field_names_and_required_flags():
    assert field_names()[:3] == ["number", "kind", "customer"]
    flags = describe_fields()
    assert flags["items"] is True and flags["customer"] is True
    assert flags["reference"] is False and flags["kind"] is False
