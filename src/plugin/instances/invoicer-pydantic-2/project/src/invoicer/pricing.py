"""Money: line totals, subtotal, tax, total and discounts. All amounts are Decimals to the cent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import List

from invoicer.errors import InvoiceError
from invoicer.models import CENTS, Invoice
from invoicer.settings import BillingSettings


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def line_totals(invoice: Invoice) -> List[dict]:
    """Each line as a dict with its gross and net amounts added."""
    rows = []
    for item in invoice.items:
        row = item.dict()
        row["gross"] = item.gross
        row["net"] = item.net
        rows.append(row)
    return rows


def subtotal(invoice: Invoice) -> Decimal:
    return invoice.subtotal


def tax(invoice: Invoice, settings: BillingSettings) -> Decimal:
    return _cents(invoice.subtotal * settings.tax_rate)


def total(invoice: Invoice, settings: BillingSettings) -> Decimal:
    return _cents(invoice.subtotal + tax(invoice, settings))


def late_fee(invoice: Invoice, settings: BillingSettings, days_late: int) -> Decimal:
    """A flat percentage of the total once an invoice is late, zero otherwise."""
    if days_late <= 0:
        return Decimal("0.00")
    return _cents(total(invoice, settings) * settings.late_fee_pct / Decimal(100))


def apply_discount(invoice: Invoice, pct: Decimal) -> Invoice:
    """A new invoice with every line discounted by ``pct`` percent; the original is unchanged."""
    pct = Decimal(pct)
    if pct < 0 or pct > 100:
        raise InvoiceError(f"discount must be between 0 and 100 percent, not {pct}")
    items = [item.copy(update={"discount_pct": pct}) for item in invoice.items]
    return invoice.copy(update={"items": items})


def split_by_sku(invoice: Invoice) -> dict:
    """Net amount per SKU, merging repeated SKUs."""
    totals: dict = {}
    for item in invoice.items:
        totals[item.sku] = _cents(totals.get(item.sku, Decimal("0")) + item.net)
    return totals
