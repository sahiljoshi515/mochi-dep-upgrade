"""How the API writes JSON: dates as ISO strings, decimals as strings, sets as sorted lists."""

from datetime import date, datetime
from decimal import Decimal

from flask.json import JSONEncoder

from notes.store import Note


class NotesJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat(timespec="seconds")
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (set, frozenset)):
            return sorted(obj)
        if isinstance(obj, Note):
            return obj.to_dict()
        return super().default(obj)
