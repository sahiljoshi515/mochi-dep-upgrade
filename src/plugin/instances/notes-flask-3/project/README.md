# notes

A small Flask application: a JSON API and two HTML pages over an in-memory
note store.

- `notes.create_app(config=None)` builds the app. By default the store is
  seeded with three notes before the first request is served; pass
  `{"SEED": False}` for an empty store.
- JSON responses keep their keys in insertion order, write non-ASCII text as
  UTF-8 (not `\uXXXX` escapes), dates as ISO `YYYY-MM-DD`, decimals as strings
  and sets as sorted lists.
- `GET /api/notes`, `POST /api/notes`, `GET|DELETE /api/notes/<id>`,
  `GET /api/notes/<id>/export` (a text download), `GET /api/tags`,
  `GET /api/search?q=`.
- `GET /` lists the notes; `GET /notes/<id>` shows one, with its body escaped.

```bash
uv sync
uv run pytest
```
