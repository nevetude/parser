from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the parser thread
            conn.execute("PRAGMA busy_timeout=15000")

    Base.metadata.create_all(engine)  # swap for Alembic once the schema settles
    return sessionmaker(engine, expire_on_commit=False)
