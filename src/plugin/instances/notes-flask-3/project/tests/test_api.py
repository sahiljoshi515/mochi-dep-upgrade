import pytest

from notes import create_app


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SEED": False})
    with app.test_client() as client:
        yield client


def test_empty_store_lists_nothing(client):
    response = client.get("/api/notes")
    assert response.status_code == 200
    assert response.get_json() == {"notes": [], "count": 0}
    assert response.headers["X-Note-Count"] == "0"


def test_create_get_and_delete(client):
    created = client.post("/api/notes", json={"title": " Groceries ", "body": "milk", "tags": ["Home", "food "]})
    assert created.status_code == 201
    note = created.get_json()
    assert note["title"] == "Groceries" and note["tags"] == ["food", "home"] and note["pinned"] is False
    assert created.headers["Location"].endswith(f"/api/notes/{note['id']}")

    fetched = client.get(f"/api/notes/{note['id']}")
    assert fetched.status_code == 200 and fetched.get_json()["body"] == "milk"
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/notes/{note['id']}").status_code == 404
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404


def test_title_is_required(client):
    assert client.post("/api/notes", json={"title": "  "}).status_code == 400
    assert client.post("/api/notes", json=["not", "a", "dict"]).status_code == 400
    assert client.post("/api/notes", json={"title": "x", "created": "not-a-date"}).status_code == 400


def test_order_tags_and_search(client):
    client.post("/api/notes", json={"title": "Old", "created": "2026-01-01", "tags": ["a"]})
    client.post("/api/notes", json={"title": "New", "created": "2026-02-01", "tags": ["a", "b"]})
    client.post("/api/notes", json={"title": "Pinned", "created": "2025-12-01", "pinned": True})
    titles = [note["title"] for note in client.get("/api/notes").get_json()["notes"]]
    assert titles == ["Pinned", "New", "Old"]
    assert client.get("/api/tags").get_json() == {"a": 2, "b": 1}
    found = client.get("/api/search?q=new").get_json()
    assert found["count"] == 1 and found["results"][0]["title"] == "New"
    assert client.get("/api/search").get_json()["results"] == []
