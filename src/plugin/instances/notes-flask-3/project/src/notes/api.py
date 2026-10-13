"""The JSON API under /api."""

import io
from datetime import date

from flask import Blueprint, abort, current_app, jsonify, request, send_file, url_for

from notes.slugs import export_filename, quoted_slug
from notes.store import NoteStore

api = Blueprint("api", __name__, url_prefix="/api")


def store() -> NoteStore:
    return current_app.extensions["notes_store"]


@api.get("/notes")
def list_notes():
    notes = store().all()
    response = jsonify({"notes": [note.to_dict() for note in notes], "count": len(notes)})
    response.headers["X-Note-Count"] = str(len(notes))
    return response


@api.post("/notes")
def create_note():
    data = request.get_json()
    if not isinstance(data, dict) or not str(data.get("title", "")).strip():
        abort(400, "a note needs a title")
    created = data.get("created")
    try:
        note = store().add(
            data["title"],
            body=str(data.get("body", "")),
            tags=data.get("tags", []),
            created=date.fromisoformat(created) if created else None,
            pinned=bool(data.get("pinned", False)),
        )
    except (TypeError, ValueError) as error:
        abort(400, str(error))
    response = jsonify(note.to_dict())
    response.status_code = 201
    response.headers["Location"] = url_for("api.get_note", note_id=note.id)
    response.headers["Link"] = f'</notes/{quoted_slug(note.title)}>; rel="alternate"'
    return response


@api.get("/notes/<int:note_id>")
def get_note(note_id: int):
    note = store().get(note_id)
    if note is None:
        abort(404)
    return jsonify(note.to_dict())


@api.delete("/notes/<int:note_id>")
def delete_note(note_id: int):
    if not store().delete(note_id):
        abort(404)
    return "", 204


@api.get("/notes/<int:note_id>/export")
def export_note(note_id: int):
    note = store().get(note_id)
    if note is None:
        abort(404)
    text = f"# {note.title}\n\n{note.body}\n\ntags: {', '.join(sorted(note.tags))}\ncreated: {note.created.isoformat()}\n"
    name = export_filename(note.title).split("/")[-1]
    return send_file(io.BytesIO(text.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name=name)


@api.get("/tags")
def tags():
    return jsonify(store().tag_counts())


@api.get("/search")
def search():
    query = request.args.get("q", "")
    found = store().search(query)
    return jsonify({"query": query, "results": [note.to_dict() for note in found], "count": len(found)})
