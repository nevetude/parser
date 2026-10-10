"""Genius payload -> rows. Stubs (id + name) are created for anything referenced but not yet fetched."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Album, AlbumArtist, AlbumTrack, Artist, ArtistRelationship, Song, SongCredit, now,
)

SOCIAL = ("twitter", "instagram", "facebook")


def _set_release(row: Album | Song, p: dict[str, Any]) -> None:
    c = p.get("release_date_components") or {}
    row.release_year, row.release_month, row.release_day = c.get("year"), c.get("month"), c.get("day")
    row.release_date_display = p.get("release_date_for_display")


# -- artists ----------------------------------------------------------------

def touch_artist(s: Session, d: dict[str, Any]) -> Artist:
    """Make sure the artist exists; fill basic fields only while it is still a stub."""
    row = s.get(Artist, d["id"])
    if row is None:
        row = Artist(id=d["id"], name=d["name"])
        s.add(row)
    if not row.loaded:
        row.name = d["name"]
        row.url = d.get("url") or row.url
        row.image_url = d.get("image_url") or row.image_url
        row.header_image_url = d.get("header_image_url") or row.header_image_url
    s.flush()
    return row


def save_artist(s: Session, p: dict[str, Any]) -> Artist:
    rels = p.get("artist_relationships") or []
    row = s.get(Artist, p["id"]) or Artist(id=p["id"])
    row.name, row.url = p["name"], p.get("url")
    row.image_url, row.header_image_url = p.get("image_url"), p.get("header_image_url")
    plain = (p.get("description") or {}).get("plain")
    row.description = plain if plain and plain != "?" else None
    row.alternate_names = p.get("alternate_names") or []
    row.social = {k: p[f"{k}_name"] for k in SOCIAL if p.get(f"{k}_name")}
    row.followers_count = p.get("followers_count")
    row.is_verified = bool(p.get("is_verified"))
    row.is_group = any(r["relationship_type"] == "members" and r["artists"] for r in rels)
    row.loaded, row.raw, row.fetched_at = True, p, now()
    s.add(row)
    s.flush()

    wanted = set()
    for rel in rels:
        for other in rel["artists"]:
            touch_artist(s, other)
            wanted.add((rel["relationship_type"], other["id"]))
    have = {
        (r.relationship_type, r.related_id): r
        for r in s.scalars(select(ArtistRelationship).where(ArtistRelationship.artist_id == row.id))
    }
    for key, r in have.items():
        if key not in wanted:
            s.delete(r)
    for rtype, rid in wanted - have.keys():
        s.add(ArtistRelationship(artist_id=row.id, relationship_type=rtype, related_id=rid))
    s.flush()
    return row


def mark_expanded(s: Session, artist_id: int) -> None:
    s.get(Artist, artist_id).expanded = True


# -- albums -----------------------------------------------------------------

def _link_album_artists(s: Session, album_id: int, artists: list[dict[str, Any]]) -> None:
    have = set(s.scalars(select(AlbumArtist.artist_id).where(AlbumArtist.album_id == album_id)))
    for a in artists:
        touch_artist(s, a)
        if a["id"] not in have:
            s.add(AlbumArtist(album_id=album_id, artist_id=a["id"]))
            have.add(a["id"])
    s.flush()


def _album_artists(p: dict[str, Any]) -> list[dict[str, Any]]:
    return p.get("primary_artists") or ([p["artist"]] if p.get("artist") else [])


def touch_album(s: Session, d: dict[str, Any]) -> Album:
    """Album stub from a list item or from a song's `album` field."""
    row = s.get(Album, d["id"])
    if row is None:
        row = Album(id=d["id"], name=d["name"])
        s.add(row)
    if not row.loaded:
        row.name, row.full_title = d["name"], d.get("full_title") or row.full_title
        row.url = d.get("url") or row.url
        row.cover_art_url = d.get("cover_art_url") or row.cover_art_url
        if d.get("release_date_components"):
            _set_release(row, d)
    s.flush()
    _link_album_artists(s, row.id, _album_artists(d))
    return row


def save_album(s: Session, p: dict[str, Any]) -> Album:
    row = s.get(Album, p["id"]) or Album(id=p["id"])
    row.name, row.full_title, row.url = p["name"], p.get("full_title"), p.get("url")
    row.cover_art_url, row.album_type = p.get("cover_art_url"), p.get("album_type")
    _set_release(row, p)
    row.loaded, row.raw, row.fetched_at = True, p, now()
    s.add(row)
    s.flush()
    _link_album_artists(s, row.id, _album_artists(p))
    return row


def save_tracklist(s: Session, album_id: int, entries: list[dict[str, Any]]) -> None:
    wanted: dict[int, dict[str, Any]] = {}
    for e in entries:
        wanted.setdefault(e["song"]["id"], e)
    for e in wanted.values():
        touch_song(s, e["song"])
    have = {t.song_id: t for t in s.scalars(select(AlbumTrack).where(AlbumTrack.album_id == album_id))}
    for sid, t in have.items():
        if sid not in wanted:
            s.delete(t)
    for sid, e in wanted.items():
        t = have.get(sid) or AlbumTrack(album_id=album_id, song_id=sid)
        t.number, t.disc_number = e.get("number"), e.get("disc_number")
        s.add(t)
    s.get(Album, album_id).tracks_loaded = True
    s.flush()


# -- songs ------------------------------------------------------------------

def touch_song(s: Session, d: dict[str, Any]) -> Song:
    row = s.get(Song, d["id"])
    if row is None:
        row = Song(id=d["id"], title=d["title"])
        s.add(row)
    if not row.loaded:
        row.title, row.full_title = d["title"], d.get("full_title")
        row.url, row.artist_names = d.get("url"), d.get("artist_names")
        _set_release(row, d)
        if d.get("primary_artist"):
            touch_artist(s, d["primary_artist"])
    s.flush()
    return row


def _credit_groups(p: dict[str, Any]) -> list[tuple[str, str, list[dict[str, Any]] | None]]:
    """(role, detail, artists) for every credit block of a song payload."""
    primary = p.get("primary_artists") or ([p["primary_artist"]] if p.get("primary_artist") else [])
    groups = [("primary", "", primary), ("featured", "", p.get("featured_artists")),
              ("writer", "", p.get("writer_artists")), ("producer", "", p.get("producer_artists"))]
    groups += [("performance", cp["label"], cp["artists"]) for cp in p.get("custom_performances") or []]
    return groups


def save_song(s: Session, p: dict[str, Any]) -> Song:
    row = s.get(Song, p["id"]) or Song(id=p["id"])
    row.title, row.full_title = p["title"], p.get("full_title")
    row.title_with_featured, row.url = p.get("title_with_featured"), p.get("url")
    row.artist_names, row.language = p.get("artist_names"), p.get("language")
    row.lyrics_state, row.recording_location = p.get("lyrics_state"), p.get("recording_location")
    plain = (p.get("description") or {}).get("plain")
    row.description = plain if plain and plain != "?" else None
    row.apple_music_id, row.media = p.get("apple_music_id"), p.get("media") or []
    _set_release(row, p)
    if p.get("album"):
        row.album_id = touch_album(s, p["album"]).id
    row.loaded, row.raw, row.fetched_at = True, p, now()
    s.add(row)
    s.flush()

    wanted: set[tuple[int, str, str]] = set()
    for role, detail, artists in _credit_groups(p):
        for a in artists or []:
            touch_artist(s, a)
            wanted.add((a["id"], role, detail))
    have = {
        (c.artist_id, c.role, c.detail): c
        for c in s.scalars(select(SongCredit).where(SongCredit.song_id == row.id))
    }
    for key, c in have.items():
        if key not in wanted:
            s.delete(c)
    for aid, role, detail in wanted - have.keys():
        s.add(SongCredit(song_id=row.id, artist_id=aid, role=role, detail=detail))
    s.flush()
    return row
