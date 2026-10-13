import json

import pytest

from notes import create_app


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SEED": False})
    with app.test_client() as client:
        yield client


def test_keys_keep_insertion_order(client):
    client.post("/api/notes", json={"title": "Order", "body": "b", "tags": ["t"], "created": "2026-01-02"})
    text = client.get("/api/notes").get_data(as_text=True)
    assert text.index('"notes"') < text.index('"count"')
    note = text[text.index("{", 1) :]
    assert note.index('"id"') < note.index('"title"') < note.index('"body"') < note.index('"tags"') < note.index('"created"') < note.index('"pinned"')


def test_dates_are_iso_and_text_is_utf8(client):
    client.post("/api/notes", json={"title": "Café", "body": "crème brûlée", "created": "2026-03-04"})
    response = client.get("/api/notes")
    raw = response.get_data()
    assert "Café".encode("utf-8") in raw and "crème brûlée".encode("utf-8") in raw
    assert b"\\u00e9" not in raw
    note = response.get_json()["notes"][0]
    assert note["created"] == "2026-03-04"
    assert json.loads(raw.decode("utf-8"))["notes"][0]["title"] == "Café"


def test_created_note_echoes_iso_date_and_alternate_link(client):
    response = client.post("/api/notes", json={"title": "Big plans!", "created": "2026-06-07"})
    assert response.get_json()["created"] == "2026-06-07"
    assert response.headers["Link"] == '</notes/big-plans>; rel="alternate"'


def test_wrong_content_type_is_415_and_bad_json_is_400(client):
    assert client.post("/api/notes", data="title=x", content_type="application/x-www-form-urlencoded").status_code == 415
    assert client.post("/api/notes", data="{not json", content_type="application/json").status_code == 400


def test_tags_are_sorted_lists_and_response_is_compact(client):
    client.post("/api/notes", json={"title": "T", "tags": ["zeta", "Alpha", "mid"]})
    response = client.get("/api/notes")
    assert response.get_json()["notes"][0]["tags"] == ["alpha", "mid", "zeta"]
    assert "\n" not in response.get_data(as_text=True).strip()
