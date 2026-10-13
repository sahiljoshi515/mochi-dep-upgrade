from decimal import Decimal

import pytest

from invoicer import invoice_from_dict, load_settings, tax
from invoicer.settings import settings_summary

PAYLOAD = {
    "number": "INV-2026-0300",
    "customer": {"name": "Margaret", "email": "margaret@example.com"},
    "issued": "2026-06-01",
    "due": "2026-06-30",
    "items": [{"sku": "APL-011", "description": "Guidance", "quantity": 1, "unit_price": "200.00"}],
}


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("INVOICER_TAX_RATE", "0.2")
    monkeypatch.setenv("INVOICER_CURRENCY", "eur")
    monkeypatch.setenv("INVOICER_PAYMENT_DAYS", "14")
    settings = load_settings()
    assert settings.tax_rate == Decimal("0.2")
    assert settings.currency == "EUR"
    assert settings.payment_days == 14
    assert tax(invoice_from_dict(PAYLOAD), settings) == Decimal("40.00")


def test_overrides_win_and_dump_is_plain(monkeypatch):
    monkeypatch.setenv("INVOICER_COMPANY_NAME", "  Env Co  ")
    settings = load_settings(company_name="Override Co")
    assert settings.model_dump()["company_name"] == "Override Co"
    assert settings_summary(load_settings())["company_name"] == "Env Co"
    assert settings_summary(settings)["tax_rate"] == Decimal("0.0825")


def test_invalid_environment_values_are_rejected(monkeypatch):
    monkeypatch.setenv("INVOICER_PAYMENT_DAYS", "0")
    with pytest.raises(Exception) as caught:
        load_settings()
    assert type(caught.value).__name__ == "ValidationError"
    monkeypatch.setenv("INVOICER_PAYMENT_DAYS", "45")
    monkeypatch.setenv("INVOICER_CURRENCY", "XXX")
    with pytest.raises(Exception) as caught:
        load_settings()
    assert type(caught.value).__name__ == "ValidationError"
