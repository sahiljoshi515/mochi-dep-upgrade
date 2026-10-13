"""Reports over invoices: summary lines, per-customer totals, overdue invoices and rows."""

from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List

from invoicer.models import CENTS, Invoice
from invoicer.pricing import total
from invoicer.settings import BillingSettings


def summary_line(invoice: Invoice, settings: BillingSettings) -> str:
    amount = total(invoice, settings)
    return f"{invoice.number} {invoice.customer.name}: {invoice.item_count} items, {amount} {invoice.currency}, due {invoice.due.isoformat()}"


def customer_totals(invoices: Iterable[Invoice], settings: BillingSettings) -> Dict[str, Decimal]:
    """Total billed per customer name, sorted by name."""
    totals: Dict[str, Decimal] = {}
    for invoice in invoices:
        name = invoice.customer.name
        totals[name] = (totals.get(name, Decimal("0")) + total(invoice, settings)).quantize(CENTS)
    return dict(sorted(totals.items()))


def overdue(invoices: Iterable[Invoice], today: date) -> List[str]:
    """Numbers of the invoices whose due date is before ``today``, oldest first."""
    late = [invoice for invoice in invoices if invoice.due < today]
    late.sort(key=lambda invoice: (invoice.due, invoice.number))
    return [invoice.number for invoice in late]


def as_rows(invoices: Iterable[Invoice], settings: BillingSettings) -> List[dict]:
    """One flat row per invoice: number, dates, currency, item count and total."""
    rows = []
    for invoice in invoices:
        row = invoice.dict(include={"number", "issued", "due", "currency"})
        row["items"] = invoice.item_count
        row["total"] = total(invoice, settings)
        rows.append(row)
    return rows


def by_currency(invoices: Iterable[Invoice], settings: BillingSettings) -> Dict[str, Decimal]:
    totals: Dict[str, Decimal] = {}
    for invoice in invoices:
        totals[invoice.currency] = (totals.get(invoice.currency, Decimal("0")) + total(invoice, settings)).quantize(CENTS)
    return totals
