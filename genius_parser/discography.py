from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .albums import AlbumService
from .artists import ArtistService
from .client import GeniusClient, GeniusError
from .models import SongCredit
from .progress import Cancelled, Reporter
from .songs import SongService

log = logging.getLogger(__name__)
_UNSET = object()


class DiscographyService:
    """The full cycle, built from the independent services (each usable on its own)."""

    def __init__(self, client: GeniusClient, session_factory: sessionmaker[Session]) -> None:
        self.sf = session_factory
        self.artists = ArtistService(client, session_factory)
        self.songs = SongService(client, session_factory)
        self.albums = AlbumService(client, session_factory, self.songs)

    def run(
        self,
        artist_id: int,
        *,
        albums_limit: int | None | object = _UNSET,
        force: bool = False,
        reporter: Reporter | None = None,
    ) -> dict[str, int]:
        """artist -> N albums (None = all) -> every track in full -> every credited artist in full."""
        limit = config.DEFAULT_ALBUMS_LIMIT if albums_limit is _UNSET else albums_limit
        rep = reporter or Reporter()
        errors = 0

        rep.update("artist", 0, 1, "Профиль артиста и группы")
        profile = self.artists.ingest(artist_id, expand=True, force=force)
        rep.set_title(profile["name"])

        rep.update("albums", 0, 0, "Список альбомов")
        listed = self.albums.list_for_artist(artist_id, limit)
        for album in listed:
            self.albums.stub(album)
        rep.log(f"Найдено альбомов: {len(listed)}")

        song_ids: set[int] = set()
        for i, album in enumerate(listed, 1):
            rep.update("tracks", i - 1, len(listed), f"Альбом: {album['name']}")
            try:
                ids = self.albums.ingest(
                    album["id"], force=force,
                    on_track=lambda n, total, a=album, i=i: rep.update(
                        "tracks", i - 1, len(listed), f"{a['name']}: трек {n}/{total}"),
                )
                song_ids.update(ids)
            except GeniusError as exc:
                errors += 1
                rep.log(f"Пропущен альбом {album['id']} ({album['name']}): {exc}")
        rep.update("tracks", len(listed), len(listed), "Треки сохранены")

        credited = self._credited_artists(song_ids)
        for i, aid in enumerate(credited, 1):
            rep.update("credits", i - 1, len(credited), f"Артист {i}/{len(credited)}")
            try:
                self.artists.ingest(aid, expand=True, force=force)
            except GeniusError as exc:
                errors += 1
                rep.log(f"Пропущен артист {aid}: {exc}")
        rep.update("credits", len(credited), len(credited), "Готово")

        summary = {"albums": len(listed), "songs": len(song_ids), "artists": len(credited), "errors": errors}
        rep.log(f"Итого: {summary}")
        return summary

    def _credited_artists(self, song_ids: set[int]) -> list[int]:
        ids: set[int] = set()
        batch = sorted(song_ids)
        with self.sf() as s:
            for i in range(0, len(batch), 500):
                ids.update(s.scalars(
                    select(SongCredit.artist_id).where(SongCredit.song_id.in_(batch[i:i + 500])).distinct()
                ))
        return sorted(ids)


__all__ = ["DiscographyService", "Cancelled"]
