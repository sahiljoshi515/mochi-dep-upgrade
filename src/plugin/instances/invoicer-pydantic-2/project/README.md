# invoicer

Invoice models, pricing and reports for a small billing service.

- `invoicer.models`: `Customer`, `LineItem` and `Invoice`, validated with pydantic.
  Models are immutable once built; strings are stripped; unknown fields are rejected.
- `invoicer.settings`: `BillingSettings`, read from the environment with the
  `INVOICER_` prefix (`INVOICER_TAX_RATE`, `INVOICER_CURRENCY`, `INVOICER_PAYMENT_DAYS`,
  `INVOICER_COMPANY_NAME`), and `load_settings()`.
- `invoicer.pricing`: line totals, subtotal, tax and total, and `apply_discount`,
  which returns a new invoice and leaves the original alone.
- `invoicer.serialization`: JSON in and out (`invoice_to_json` writes sorted keys and
  ISO dates), dict in and out, and the JSON schema.
- `invoicer.validation`: `validate_payload` turns a raw payload's validation errors
  into `Problem(loc, type, message)` records, with pydantic's own error type codes.
- `invoicer.reports`: summary lines, per-customer totals, overdue invoices and rows.

```bash
uv sync
uv run pytest
```
