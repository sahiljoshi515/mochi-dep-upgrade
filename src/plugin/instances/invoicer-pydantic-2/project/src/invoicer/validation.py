"""Validating raw payloads before they become invoices: every problem as a plain record."""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from pydantic import ValidationError

from invoicer.models import Invoice


@dataclass(frozen=True)
class Problem:
    loc: Tuple
    type: str
    message: str

    @property
    def field(self) -> str:
        return ".".join(str(part) for part in self.loc)


def validate_payload(data: dict) -> List[Problem]:
    """Every validation problem of ``data`` as an invoice, in pydantic's order; [] when it is valid.
    ``type`` is pydantic's own error type code."""
    try:
        Invoice.parse_obj(data)
    except ValidationError as error:
        return [Problem(loc=tuple(item["loc"]), type=item["type"], message=item["msg"]) for item in error.errors()]
    return []


def is_valid(data: dict) -> bool:
    return not validate_payload(data)


def problems_by_field(data: dict) -> Dict[str, List[str]]:
    """Problem messages grouped by dotted field name."""
    grouped: Dict[str, List[str]] = {}
    for problem in validate_payload(data):
        grouped.setdefault(problem.field, []).append(problem.message)
    return grouped


def field_names() -> List[str]:
    """The invoice's field names, in declaration order."""
    return list(Invoice.__fields__)


def describe_fields() -> Dict[str, bool]:
    """Each invoice field and whether it is required."""
    return {name: field.required for name, field in Invoice.__fields__.items()}
