from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import repo
from .client import GeniusClient
from .models import Album, AlbumTrack
from .songs import SongService


class AlbumService:
    def __init__(self, client: GeniusClient, session_factory: sessionmaker[Session], songs: SongService) -> None:
        self.client = client
        self.sf = session_factory
        self.songs = songs

    def list_for_artist(self, artist_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        """Live list of an artist's albums, newest first. limit=None -> all."""
        return self.client.artist_albums(artist_id, limit)

    def fetch(self, album_id: int) -> dict[str, Any]:
        """Live album details and tracklist, nothing is stored."""
        return {**self.client.album(album_id), "tracks": self.client.album_tracks(album_id)}

    def ingest(
        self,
        album_id: int,
        *,
        with_songs: bool = True,
        force: bool = False,
        on_track: Callable[[int, int], None] | None = None,
    ) -> list[int]:
        """Store the album, its tracklist (with numbers) and, by default, every track in full.

        Returns the song ids in album order.
        """
        with self.sf() as s:
            row = s.get(Album, album_id)
            fresh = bool(row and row.loaded and row.tracks_loaded and not force)
        if not fresh:
            payload = self.client.album(album_id)
            tracks = self.client.album_tracks(album_id)
            with self.sf.begin() as s:
                repo.save_album(s, payload)
                repo.save_tracklist(s, album_id, tracks)

        with self.sf() as s:
            song_ids = list(s.scalars(
                select(AlbumTrack.song_id).where(AlbumTrack.album_id == album_id)
                .order_by(AlbumTrack.disc_number, AlbumTrack.number, AlbumTrack.pk)
            ))
        if with_songs:
            for i, song_id in enumerate(song_ids, 1):
                self.songs.ingest(song_id, force=force)
                if on_track:
                    on_track(i, len(song_ids))
        return song_ids

    def stub(self, album: dict[str, Any]) -> None:
        """Remember an album from a list item so it is visible before its details are fetched."""
        with self.sf.begin() as s:
            repo.touch_album(s, album)
