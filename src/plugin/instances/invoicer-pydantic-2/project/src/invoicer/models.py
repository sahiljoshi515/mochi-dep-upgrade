"""The invoice domain: customers, line items and invoices.

Every model is immutable once built, strips its strings and rejects unknown fields.
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, root_validator, validator

CURRENCIES = ("USD", "EUR", "GBP")
NUMBER_PATTERN = r"^INV-\d{4}-\d{4}$"
SKU_PATTERN = r"^[A-Z]{3}-\d{3}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"
VAT_PATTERN = r"^[A-Z]{2}[0-9A-Z]{2,12}$"
CENTS = Decimal("0.01")


class Customer(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., regex=EMAIL_PATTERN)
    vat_id: Optional[str] = Field(None, regex=VAT_PATTERN)
    country: str = Field("US", min_length=2, max_length=2)

    class Config:
        anystr_strip_whitespace = True
        allow_mutation = False
        extra = "forbid"

    @validator("country")
    def country_code_is_upper(cls, value: str) -> str:
        return value.upper()

    @validator("email")
    def email_is_lower(cls, value: str) -> str:
        return value.lower()


class LineItem(BaseModel):
    sku: str = Field(..., regex=SKU_PATTERN)
    description: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., gt=0, le=10000)
    unit_price: Decimal = Field(..., ge=0, max_digits=10, decimal_places=2)
    discount_pct: Decimal = Field(Decimal("0"), ge=0, le=100)

    class Config:
        anystr_strip_whitespace = True
        allow_mutation = False
        extra = "forbid"

    @validator("sku", pre=True)
    def sku_is_upper(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @property
    def gross(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENTS)

    @property
    def net(self) -> Decimal:
        kept = (Decimal(100) - self.discount_pct) / Decimal(100)
        return (self.unit_price * self.quantity * kept).quantize(CENTS)


class Invoice(BaseModel):
    number: str = Field(..., regex=NUMBER_PATTERN)
    kind: str = Field("invoice", const=True)
    customer: Customer
    issued: date
    due: date
    currency: str = Field("USD", min_length=3, max_length=3)
    items: List[LineItem] = Field(..., min_items=1, max_items=50)
    reference: Optional[str]
    notes: Optional[str] = Field(None, max_length=500)

    class Config:
        anystr_strip_whitespace = True
        allow_mutation = False
        extra = "forbid"

    @validator("currency")
    def currency_is_known(cls, value: str) -> str:
        value = value.upper()
        if value not in CURRENCIES:
            raise ValueError(f"unsupported currency {value!r}; use one of {', '.join(CURRENCIES)}")
        return value

    @root_validator
    def due_is_not_before_issued(cls, values):
        issued, due = values.get("issued"), values.get("due")
        if issued is not None and due is not None and due < issued:
            raise ValueError("due date is before the issue date")
        return values

    @property
    def subtotal(self) -> Decimal:
        return sum((item.net for item in self.items), Decimal("0")).quantize(CENTS)

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    def with_reference(self, reference: str) -> "Invoice":
        return self.copy(update={"reference": reference.strip()})
