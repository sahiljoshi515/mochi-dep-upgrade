"""The HTML pages: the list and one note."""

from flask import Blueprint, Markup, abort, current_app, escape, render_template_string

from notes.store import NoteStore

pages = Blueprint("pages", __name__)

LIST_PAGE = """<!doctype html>
<title>Notes</title>
<h1>Notes</h1>
<ul>
{% for note in notes %}  <li id="note-{{ note.id }}">{{ note|tagline }}</li>
{% endfor %}</ul>
<p>{{ count }} note(s)</p>
"""

NOTE_PAGE = """<!doctype html>
<title>{{ note.title }}</title>
<h1>{{ note.title }}</h1>
<p class="meta">{{ note.created.isoformat() }} · {{ tags }}</p>
<div class="body">{{ body }}</div>
"""


def store() -> NoteStore:
    return current_app.extensions["notes_store"]


def render_body(body: str) -> Markup:
    """Paragraphs separated by blank lines, every line escaped."""
    paragraphs = [part for part in body.split("\n\n") if part.strip()]
    return Markup("".join(f"<p>{'<br>'.join(escape(line) for line in part.splitlines())}</p>" for part in paragraphs))


@pages.get("/")
def index():
    notes = store().all()
    return render_template_string(LIST_PAGE, notes=notes, count=len(notes))


@pages.get("/notes/<int:note_id>")
def show(note_id: int):
    note = store().get(note_id)
    if note is None:
        abort(404)
    return render_template_string(NOTE_PAGE, note=note, tags=", ".join(sorted(note.tags)), body=render_body(note.body))
