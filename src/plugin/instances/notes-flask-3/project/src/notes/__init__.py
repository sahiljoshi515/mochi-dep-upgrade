"""notes: a small Flask API and site for personal notes."""

from notes.app import create_app
from notes.store import Note, NoteStore, seed_notes

__all__ = ["Note", "NoteStore", "create_app", "seed_notes"]
