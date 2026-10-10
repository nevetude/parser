"""Read side: stored data shaped for the UI."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Album, AlbumArtist, AlbumTrack, Artist, ArtistRelationship, Song, SongCredit


def _artist_brief(a: Artist) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "image_url": a.image_url, "is_group": a.is_group, "loaded": a.loaded}


def _date(row: Album | Song) -> str:
    parts = [row.release_year, row.release_month, row.release_day]
    return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p) if row.release_year else ""


class Queries:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.sf = session_factory

    def list_artists(self, q: str = "", groups_only: bool = False, limit: int = 200) -> dict[str, Any]:
        with self.sf() as s:
            stmt = select(Artist).where(Artist.loaded)
            if q:
                stmt = stmt.where(Artist.name.ilike(f"%{q}%"))
            if groups_only:
                stmt = stmt.where(Artist.is_group)
            total = s.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = s.scalars(stmt.order_by(Artist.name).limit(limit)).all()
            counts = dict(s.execute(
                select(AlbumArtist.artist_id, func.count()).where(AlbumArtist.artist_id.in_([a.id for a in rows]))
                .group_by(AlbumArtist.artist_id)
            ).all()) if rows else {}
            return {"total": total, "items": [{**_artist_brief(a), "albums": counts.get(a.id, 0)} for a in rows]}

    def artist(self, artist_id: int) -> dict[str, Any] | None:
        with self.sf() as s:
            a = s.get(Artist, artist_id)
            if a is None:
                return None
            rels: dict[str, list[dict[str, Any]]] = {}
            for rel, other in s.execute(
                select(ArtistRelationship, Artist).join(Artist, Artist.id == ArtistRelationship.related_id)
                .where(ArtistRelationship.artist_id == a.id).order_by(Artist.name)
            ):
                rels.setdefault(rel.relationship_type, []).append(_artist_brief(other))
            albums = s.execute(
                select(Album, func.count(AlbumTrack.pk)).join(AlbumArtist, AlbumArtist.album_id == Album.id)
                .outerjoin(AlbumTrack, AlbumTrack.album_id == Album.id)
                .where(AlbumArtist.artist_id == a.id).group_by(Album.id)
                .order_by(Album.release_year.desc().nulls_last(), Album.release_month.desc().nulls_last(),
                          Album.release_day.desc().nulls_last())
            ).all()
            return {
                **_artist_brief(a), "url": a.url, "header_image_url": a.header_image_url,
                "description": a.description, "alternate_names": a.alternate_names, "social": a.social,
                "followers_count": a.followers_count, "is_verified": a.is_verified, "expanded": a.expanded,
                "relationships": rels,
                "albums": [
                    {"id": al.id, "name": al.name, "cover_art_url": al.cover_art_url, "date": _date(al),
                     "tracks": n, "loaded": al.tracks_loaded}
                    for al, n in albums
                ],
            }

    def album(self, album_id: int) -> dict[str, Any] | None:
        with self.sf() as s:
            al = s.get(Album, album_id)
            if al is None:
                return None
            artists = s.scalars(
                select(Artist).join(AlbumArtist, AlbumArtist.artist_id == Artist.id)
                .where(AlbumArtist.album_id == al.id)
            ).all()
            rows = s.execute(
                select(AlbumTrack, Song).join(Song, Song.id == AlbumTrack.song_id)
                .where(AlbumTrack.album_id == al.id)
                .order_by(AlbumTrack.disc_number, AlbumTrack.number, AlbumTrack.pk)
            ).all()
            credits: dict[int, list[dict[str, Any]]] = {}
            if rows:
                for c, a in s.execute(
                    select(SongCredit, Artist).join(Artist, Artist.id == SongCredit.artist_id)
                    .where(SongCredit.song_id.in_([song.id for _, song in rows]))
                ):
                    credits.setdefault(c.song_id, []).append(
                        {"id": a.id, "name": a.name, "role": c.role, "detail": c.detail})
            return {
                "id": al.id, "name": al.name, "full_title": al.full_title, "url": al.url,
                "cover_art_url": al.cover_art_url, "album_type": al.album_type, "date": _date(al),
                "loaded": al.loaded, "tracks_loaded": al.tracks_loaded,
                "artists": [{"id": a.id, "name": a.name} for a in artists],
                "tracks": [
                    {"number": t.number, "disc_number": t.disc_number, "id": song.id, "title": song.title,
                     "url": song.url, "loaded": song.loaded, "language": song.language,
                     "credits": credits.get(song.id, [])}
                    for t, song in rows
                ],
            }

    def song(self, song_id: int) -> dict[str, Any] | None:
        with self.sf() as s:
            song = s.get(Song, song_id)
            if song is None:
                return None
            credits = [
                {"id": a.id, "name": a.name, "role": c.role, "detail": c.detail}
                for c, a in s.execute(
                    select(SongCredit, Artist).join(Artist, Artist.id == SongCredit.artist_id)
                    .where(SongCredit.song_id == song.id)
                )
            ]
            return {
                "id": song.id, "title": song.title, "full_title": song.full_title, "url": song.url,
                "date": _date(song), "language": song.language, "description": song.description,
                "recording_location": song.recording_location, "media": song.media,
                "album_id": song.album_id, "loaded": song.loaded, "credits": credits,
            }

    def stats(self) -> dict[str, int]:
        with self.sf() as s:
            return {
                "artists": s.scalar(select(func.count()).select_from(Artist).where(Artist.loaded)),
                "groups": s.scalar(select(func.count()).select_from(Artist).where(Artist.is_group)),
                "albums": s.scalar(select(func.count()).select_from(Album).where(Album.tracks_loaded)),
                "songs": s.scalar(select(func.count()).select_from(Song).where(Song.loaded)),
            }
