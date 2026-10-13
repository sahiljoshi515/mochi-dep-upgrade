"""An in-memory note store."""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional


@dataclass
class Note:
    id: int
    title: str
    body: str
    tags: set = field(default_factory=set)
    created: date = field(default_factory=date.today)
    pinned: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "tags": sorted(self.tags),
            "created": self.created,
            "pinned": self.pinned,
        }


class NoteStore:
    def __init__(self) -> None:
        self._notes: Dict[int, Note] = {}
        self._next = 1

    def add(self, title: str, body: str = "", tags: Iterable[str] = (), created: Optional[date] = None, pinned: bool = False) -> Note:
        title = title.strip()
        if not title:
            raise ValueError("a note needs a title")
        note = Note(
            id=self._next,
            title=title,
            body=body,
            tags={tag.strip().lower() for tag in tags if tag.strip()},
            created=created or date.today(),
            pinned=pinned,
        )
        self._notes[note.id] = note
        self._next += 1
        return note

    def get(self, note_id: int) -> Optional[Note]:
        return self._notes.get(note_id)

    def all(self) -> List[Note]:
        """Pinned notes first, then newest first, then by id."""
        return sorted(self._notes.values(), key=lambda note: (not note.pinned, -note.created.toordinal(), note.id))

    def delete(self, note_id: int) -> bool:
        return self._notes.pop(note_id, None) is not None

    def search(self, text: str) -> List[Note]:
        needle = text.strip().lower()
        if not needle:
            return []
        return [note for note in self.all() if needle in note.title.lower() or needle in note.body.lower()]

    def tag_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for note in self._notes.values():
            for tag in note.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items()))

    def is_empty(self) -> bool:
        return not self._notes

    def count(self) -> int:
        return len(self._notes)


def seed_notes(store: NoteStore) -> None:
    """Three notes to start with."""
    store.add("Café notes", "Try the new espresso — it's great.", tags=["food", "ideas"], created=date(2026, 1, 2))
    store.add("Reading list", "Dune\nThe Left Hand of Darkness", tags=["books"], created=date(2026, 2, 14))
    store.add("Standup", "Blockers: none <yet>", tags=["work"], created=date(2026, 3, 1), pinned=True)
