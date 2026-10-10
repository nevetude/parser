from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from . import repo
from .client import GeniusClient
from .models import Song


class SongService:
    def __init__(self, client: GeniusClient, session_factory: sessionmaker[Session]) -> None:
        self.client = client
        self.sf = session_factory

    def fetch(self, song_id: int) -> dict[str, Any]:
        """Live song, nothing is stored."""
        return self.client.song(song_id)

    def ingest(self, song_id: int, *, force: bool = False) -> dict[str, Any]:
        """Store the full song with all credits (credited artists become stubs). Returns the payload."""
        with self.sf() as s:
            row = s.get(Song, song_id)
            if row and row.loaded and row.raw and not force:
                return row.raw
        payload = self.client.song(song_id)
        with self.sf.begin() as s:
            repo.save_song(s, payload)
        return payload
