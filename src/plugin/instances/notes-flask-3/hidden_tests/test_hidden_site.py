import pytest

from notes import create_app
from notes.slugs import export_filename, quoted_slug


@pytest.fixture
def seeded():
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


def test_seeded_notes_are_served_on_the_first_request(seeded):
    listed = seeded.get("/api/notes").get_json()
    assert listed["count"] == 3
    assert [note["title"] for note in listed["notes"]] == ["Standup", "Reading list", "Café notes"]
    assert listed["notes"][0]["pinned"] is True
    assert seeded.get("/api/tags").get_json() == {"books": 1, "food": 1, "ideas": 1, "work": 1}
    assert seeded.get("/api/notes").get_json()["count"] == 3


def test_export_is_a_text_download_named_after_the_slug(seeded):
    response = seeded.get("/api/notes/1/export")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "cafe-notes.txt" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert text.startswith("# Café notes\n\n") and "tags: food, ideas\ncreated: 2026-01-02\n" in text
    assert seeded.get("/api/notes/99/export").status_code == 404


def test_pages_escape_note_text(seeded):
    page = seeded.get("/notes/3").get_data(as_text=True)
    assert "Blockers: none &lt;yet&gt;" in page
    assert "<yet>" not in page
    index = seeded.get("/").get_data(as_text=True)
    assert "<strong>Standup</strong> <small>work</small>" in index
    assert 'id="note-3"' in index.split('id="note-2"')[0]


def test_slug_helpers():
    assert quoted_slug("Café & crème") == "cafe-creme"
    assert quoted_slug("a b") == "a-b"
    assert export_filename("Reading list") == "exports/reading-list.txt"
    assert export_filename("../etc/passwd") == "exports/etc-passwd.txt"
