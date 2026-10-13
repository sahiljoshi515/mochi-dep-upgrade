"""Invoices as JSON and plain dicts, and the JSON schema clients validate against."""

from invoicer.models import Invoice


def invoice_to_json(invoice: Invoice) -> str:
    """Stable JSON: sorted keys, two-space indent, dates as ISO strings, decimals as strings."""
    return invoice.json(indent=2, sort_keys=True)


def invoice_from_json(text: str) -> Invoice:
    return Invoice.parse_raw(text)


def invoice_from_dict(data: dict) -> Invoice:
    return Invoice.parse_obj(data)


def invoice_schema() -> dict:
    """The invoice's JSON schema."""
    return Invoice.schema()


def to_record(invoice: Invoice) -> dict:
    """The invoice as a flat record for storage: the customer's name only, no notes."""
    data = invoice.dict(exclude={"notes", "customer"})
    data["customer_name"] = invoice.customer.name
    data["subtotal"] = invoice.subtotal
    return data


def items_as_dicts(invoice: Invoice) -> list:
    """Each line as plain values (strings for decimals), ready for JSON."""
    return [
        {
            "sku": item.sku,
            "description": item.description,
            "quantity": item.quantity,
            "unit_price": str(item.unit_price),
            "discount_pct": str(item.discount_pct),
        }
        for item in invoice.items
    ]
