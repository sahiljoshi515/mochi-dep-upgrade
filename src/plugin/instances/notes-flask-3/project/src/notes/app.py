"""The application factory."""

from flask import Flask

from notes.api import api
from notes.filters import register_filters
from notes.json_support import NotesJSONEncoder
from notes.pages import pages
from notes.store import NoteStore, seed_notes


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="notes-dev",
        SEED=True,
        JSON_SORT_KEYS=False,
        JSON_AS_ASCII=False,
        JSONIFY_PRETTYPRINT_REGULAR=False,
    )
    if config:
        app.config.update(config)
    app.json_encoder = NotesJSONEncoder

    store = NoteStore()
    app.extensions["notes_store"] = store
    app.register_blueprint(api)
    app.register_blueprint(pages)
    register_filters(app)

    @app.before_first_request
    def seed() -> None:
        if app.config["SEED"] and store.is_empty():
            seed_notes(store)

    return app
