"""Billing settings, from the environment (prefix ``INVOICER_``) or explicit overrides."""

from decimal import Decimal

from pydantic import BaseSettings, Field, validator

from invoicer.models import CURRENCIES


class BillingSettings(BaseSettings):
    tax_rate: Decimal = Field(Decimal("0.0825"), ge=0, le=1)
    currency: str = "USD"
    payment_days: int = Field(30, ge=1, le=365)
    company_name: str = Field("Acme Billing", min_length=1)
    late_fee_pct: Decimal = Field(Decimal("1.5"), ge=0, le=20)

    class Config:
        env_prefix = "INVOICER_"
        case_sensitive = False
        anystr_strip_whitespace = True

    @validator("currency")
    def currency_is_known(cls, value: str) -> str:
        value = value.upper()
        if value not in CURRENCIES:
            raise ValueError(f"unsupported currency {value!r}")
        return value


def load_settings(**overrides) -> BillingSettings:
    """Settings from the environment, with explicit keyword overrides winning."""
    return BillingSettings(**overrides)


def settings_summary(settings: BillingSettings) -> dict:
    """The settings as plain values, for logging."""
    return settings.dict()
