from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from . import repo
from .client import GeniusClient
from .models import Artist

log = logging.getLogger(__name__)


def related(payload: dict[str, Any], relationship_type: str) -> list[dict[str, Any]]:
    return [
        a for r in payload.get("artist_relationships") or []
        if r["relationship_type"] == relationship_type for a in r["artists"]
    ]


class ArtistService:
    def __init__(self, client: GeniusClient, session_factory: sessionmaker[Session]) -> None:
        self.client = client
        self.sf = session_factory

    def search(self, query: str, pages: int = 3) -> list[dict[str, Any]]:
        """Artists matching a name. Genius only searches songs, so we collect their primary artists."""
        found: dict[int, dict[str, Any]] = {}
        for page in range(1, pages + 1):
            hits = self.client.search(query, page)
            for hit in hits:
                a = hit["primary_artist"]
                found.setdefault(a["id"], {k: a.get(k) for k in ("id", "name", "url", "image_url")})
            if not hits:
                break
        return list(found.values())

    def fetch(self, artist_id: int) -> dict[str, Any]:
        """Live profile, nothing is stored."""
        return self.client.artist(artist_id)

    def ingest(self, artist_id: int, *, expand: bool = True, force: bool = False) -> dict[str, Any]:
        """Store an artist profile and return its payload.

        expand=True also pulls in, one level only:
          * the groups the artist belongs to (`member_of`) and every member of those groups,
          * the artist's own members, if it is a group.
        Those extra artists are stored with expand=False, so the chain stops there.
        """
        with self.sf() as s:
            row = s.get(Artist, artist_id)
            cached = row.raw if row and row.loaded and row.raw and not force else None
            satisfied = cached is not None and (row.expanded or not expand)
        if satisfied:
            return cached

        payload = cached
        if payload is None:
            payload = self.client.artist(artist_id)
            with self.sf.begin() as s:
                repo.save_artist(s, payload)

        if expand:
            for member in related(payload, "members"):
                self.ingest(member["id"], expand=False, force=force)
            for group in related(payload, "member_of"):
                group_payload = self.ingest(group["id"], expand=False, force=force)
                for member in related(group_payload, "members"):
                    self.ingest(member["id"], expand=False, force=force)
            with self.sf.begin() as s:
                repo.mark_expanded(s, artist_id)
        return payload
