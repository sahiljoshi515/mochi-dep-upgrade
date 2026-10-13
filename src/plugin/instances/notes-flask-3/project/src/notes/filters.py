"""Template filters: safe HTML snippets built from note fields."""

from flask import Flask, Markup, escape

from notes.store import Note


def tagline(note: Note) -> Markup:
    """``<strong>title</strong> <small>tag, tag</small>``, with every field escaped."""
    tags = ", ".join(escape(tag) for tag in sorted(note.tags))
    return Markup(f"<strong>{escape(note.title)}</strong> <small>{tags}</small>")


def nl2br(text: str) -> Markup:
    """Escaped text with line breaks as ``<br>``."""
    return Markup("<br>".join(escape(line) for line in text.splitlines()))


def register_filters(app: Flask) -> None:
    app.add_template_filter(tagline, "tagline")
    app.add_template_filter(nl2br, "nl2br")
