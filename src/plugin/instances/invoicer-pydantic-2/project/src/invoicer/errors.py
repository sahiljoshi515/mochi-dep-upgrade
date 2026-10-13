"""The package's own errors."""


class InvoiceError(ValueError):
    """A business rule was broken: a bad discount, an unknown invoice, a date in the past."""
