"""Schema helpers: table names, reflection and creation."""

from typing import List

from sqlalchemy import Table
from sqlalchemy.engine import Engine

from ledger.db import Base, bound_metadata


def table_names(engine: Engine) -> List[str]:
    """The database's table names, sorted."""
    return sorted(engine.table_names())


def reflect_table(engine: Engine, name: str) -> Table:
    """The table ``name`` as the database describes it."""
    return Table(name, bound_metadata(engine), autoload=True)


def column_names(engine: Engine, name: str) -> List[str]:
    return [column.name for column in reflect_table(engine, name).columns]


def create_schema(engine: Engine) -> List[str]:
    Base.metadata.create_all(engine)
    return table_names(engine)


def drop_schema(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
