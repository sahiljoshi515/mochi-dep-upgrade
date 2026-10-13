import pytest

from notes import create_app
from notes.slugs import slugify


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SEED": False})
    with app.test_client() as client:
        yield client


def test_index_lists_titles(client):
    client.post("/api/notes", json={"title": "First", "tags": ["x"]})
    client.post("/api/notes", json={"title": "Second"})
    page = client.get("/").get_data(as_text=True)
    assert "<strong>First</strong> <small>x</small>" in page
    assert "<strong>Second</strong>" in page
    assert "2 note(s)" in page


def test_note_page_and_404(client):
    note = client.post("/api/notes", json={"title": "Plan", "body": "one\n\ntwo\nthree", "created": "2026-05-05"}).get_json()
    page = client.get(f"/notes/{note['id']}").get_data(as_text=True)
    assert "<h1>Plan</h1>" in page
    assert "<p>one</p><p>two<br>three</p>" in page
    assert "2026-05-05" in page
    assert client.get("/notes/999").status_code == 404


def test_slugify():
    assert slugify("Café notes!") == "cafe-notes"
    assert slugify("  ---  ") == "note"
