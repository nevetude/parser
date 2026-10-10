"""Storage schema. Key columns are real columns; the full Genius payload is kept in `raw`."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Artist(Base):
    __tablename__ = "artist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # Genius id
    name: Mapped[str] = mapped_column(String(500), index=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    header_image_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    alternate_names: Mapped[list] = mapped_column(JSON, default=list)
    social: Mapped[dict] = mapped_column(JSON, default=dict)
    followers_count: Mapped[int | None]
    is_verified: Mapped[bool] = mapped_column(default=False)
    is_group: Mapped[bool] = mapped_column(default=False, index=True)  # has non-empty `members`
    loaded: Mapped[bool] = mapped_column(default=False)    # full /artists/:id payload stored
    expanded: Mapped[bool] = mapped_column(default=False)  # its groups and their members were pulled in
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtistRelationship(Base):
    """Genius `artist_relationships`: members, member_of, ..."""

    __tablename__ = "artist_relationship"
    __table_args__ = (UniqueConstraint("artist_id", "relationship_type", "related_id"),)

    pk: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artist.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(50), index=True)
    related_id: Mapped[int] = mapped_column(ForeignKey("artist.id"), index=True)


class Album(Base):
    __tablename__ = "album"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(500), index=True)
    full_title: Mapped[str | None] = mapped_column(String(1000))
    url: Mapped[str | None] = mapped_column(String(1000))
    cover_art_url: Mapped[str | None] = mapped_column(String(1000))
    album_type: Mapped[str | None] = mapped_column(String(50))
    release_year: Mapped[int | None]
    release_month: Mapped[int | None]
    release_day: Mapped[int | None]
    release_date_display: Mapped[str | None] = mapped_column(String(50))
    loaded: Mapped[bool] = mapped_column(default=False)         # album details stored
    tracks_loaded: Mapped[bool] = mapped_column(default=False)  # tracklist stored
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlbumArtist(Base):
    __tablename__ = "album_artist"
    __table_args__ = (UniqueConstraint("album_id", "artist_id"),)

    pk: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id", ondelete="CASCADE"), index=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artist.id"), index=True)


class Song(Base):
    __tablename__ = "song"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(500), index=True)
    full_title: Mapped[str | None] = mapped_column(String(1000))
    title_with_featured: Mapped[str | None] = mapped_column(String(1000))
    url: Mapped[str | None] = mapped_column(String(1000))
    artist_names: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(String(20))
    lyrics_state: Mapped[str | None] = mapped_column(String(30))
    recording_location: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    apple_music_id: Mapped[str | None] = mapped_column(String(50))
    media: Mapped[list] = mapped_column(JSON, default=list)
    release_year: Mapped[int | None]
    release_month: Mapped[int | None]
    release_day: Mapped[int | None]
    release_date_display: Mapped[str | None] = mapped_column(String(50))
    album_id: Mapped[int | None] = mapped_column(ForeignKey("album.id"), index=True)  # Genius' primary album
    loaded: Mapped[bool] = mapped_column(default=False)
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SongCredit(Base):
    """role: primary | featured | writer | producer | performance (detail = e.g. 'Guitar')."""

    __tablename__ = "song_credit"
    __table_args__ = (UniqueConstraint("song_id", "artist_id", "role", "detail"),)

    pk: Mapped[int] = mapped_column(primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("song.id", ondelete="CASCADE"), index=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artist.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(200), default="")


class AlbumTrack(Base):
    """A song's place on an album; one song may appear on several albums."""

    __tablename__ = "album_track"
    __table_args__ = (UniqueConstraint("album_id", "song_id"),)

    pk: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("album.id", ondelete="CASCADE"), index=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("song.id"), index=True)
    number: Mapped[int | None]
    disc_number: Mapped[int | None]
