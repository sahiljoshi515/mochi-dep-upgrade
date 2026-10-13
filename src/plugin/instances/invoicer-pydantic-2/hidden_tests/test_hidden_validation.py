from invoicer import validate_payload
from invoicer.validation import problems_by_field

PAYLOAD = {
    "number": "INV-2026-0200",
    "customer": {"name": "Grace Hopper", "email": "grace@example.com"},
    "issued": "2026-04-01",
    "due": "2026-04-30",
    "items": [{"sku": "NAV-100", "description": "Compass", "quantity": 2, "unit_price": "25.00"}],
}


def test_error_type_codes_are_pydantic_v2():
    problems = validate_payload({**PAYLOAD, "number": "INV-1", "items": []})
    types = {problem.field: problem.type for problem in problems}
    assert types == {"number": "string_pattern_mismatch", "items": "too_short"}


def test_numbers_are_not_coerced_to_strings():
    problems = validate_payload({**PAYLOAD, "customer": {**PAYLOAD["customer"], "name": 123}})
    assert [(problem.field, problem.type) for problem in problems] == [("customer.name", "string_type")]


def test_quantity_and_price_bounds():
    bad = [
        {"sku": "NAV-100", "description": "Compass", "quantity": 0, "unit_price": "25.00"},
        {"sku": "NAV-100", "description": "Compass", "quantity": 1, "unit_price": "-1"},
        {"sku": "NAV-100", "description": "Compass", "quantity": 1, "unit_price": "1.234"},
    ]
    problems = validate_payload({**PAYLOAD, "items": bad})
    assert [(problem.field, problem.type) for problem in problems] == [
        ("items.0.quantity", "greater_than"),
        ("items.1.unit_price", "greater_than_equal"),
        ("items.2.unit_price", "decimal_max_places"),
    ]


def test_extra_fields_are_reported_with_their_location():
    problems = validate_payload({**PAYLOAD, "customer": {**PAYLOAD["customer"], "phone": "555"}})
    assert [(problem.field, problem.type) for problem in problems] == [("customer.phone", "extra_forbidden")]


def test_due_before_issued_is_a_model_level_problem():
    problems = validate_payload({**PAYLOAD, "due": "2026-02-01"})
    assert len(problems) == 1
    assert problems[0].loc == ()
    assert problems[0].type == "value_error"
    assert "before" in problems[0].message


def test_problems_by_field_groups_messages():
    grouped = problems_by_field({**PAYLOAD, "number": "x", "currency": "XXX"})
    assert set(grouped) == {"number", "currency"}
    assert any("XXX" in message for message in grouped["currency"])
