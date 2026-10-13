"""Engines, sessions and the declarative base."""

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


def make_engine(url: str = "sqlite://", echo: bool = False) -> Engine:
    """An engine for ``url``; the default is a private in-memory SQLite database."""
    return create_engine(url, echo=echo)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine)


def bound_metadata(engine: Engine) -> MetaData:
    """A MetaData bound to ``engine``, for reflection helpers."""
    return MetaData(bind=engine)
