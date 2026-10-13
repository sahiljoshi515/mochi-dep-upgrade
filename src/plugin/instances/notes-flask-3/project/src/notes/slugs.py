"""Slugs and safe file names for notes."""

import re
import unicodedata

from werkzeug.security import safe_join
from werkzeug.urls import url_quote

EXPORT_FOLDER = "exports"


def slugify(title: str) -> str:
    """``"Café notes!"`` -> ``"cafe-notes"``."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "note"


def quoted_slug(title: str) -> str:
    """The slug as it appears in a URL (percent-encoded, though slugs rarely need it)."""
    return url_quote(slugify(title))


def export_filename(title: str) -> str:
    """``exports/<slug>.txt``, refusing anything that would leave the export folder."""
    path = safe_join(EXPORT_FOLDER, f"{slugify(title)}.txt")
    if path is None:
        raise ValueError("unsafe export name")
    return path
