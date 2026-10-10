"""Genius HTTP client. Two backends:

* public  api.genius.com   - documented, needs the access token (artists, songs, search)
* web     genius.com/api   - undocumented, no auth (artist albums, album details, tracklists)

Thread safe: requests from all threads share one throttle.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

PUBLIC_URL = "https://api.genius.com"
WEB_URL = "https://genius.com/api"
PAGE_SIZE = 50


class GeniusError(Exception):
    pass


class GeniusNotFound(GeniusError):
    pass


class GeniusClient:
    def __init__(
        self,
        token: str,
        *,
        min_interval: float = 0.2,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self._token = token
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(timeout=30.0, transport=transport, headers={"User-Agent": "genius-parser/0.1"})
        self._lock = threading.Lock()
        self._last = 0.0

    def close(self) -> None:
        self._http.close()

    # -- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()

    def _get(self, url: str, params: dict[str, Any], *, auth: bool) -> dict[str, Any]:
        if auth and not self._token:
            raise GeniusError("GENIUS_ACCESS_TOKEN is not set")
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                resp = self._http.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise GeniusError(f"network error: {exc}") from exc
                self._sleep(2**attempt)
                continue
            if resp.status_code == 404:
                raise GeniusNotFound(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_retries:
                    raise GeniusError(f"{resp.status_code} from {url}")
                delay = _retry_after(resp) or 2**attempt
                log.warning("%s from %s, retry in %.1fs", resp.status_code, url, delay)
                self._sleep(delay)
                continue
            if resp.status_code >= 400:
                raise GeniusError(f"{resp.status_code} from {url}: {resp.text[:200]}")
            return resp.json()["response"]
        raise GeniusError("unreachable")

    def _public(self, path: str, **params: Any) -> dict[str, Any]:
        return self._get(PUBLIC_URL + path, params, auth=True)

    def _web(self, path: str, **params: Any) -> dict[str, Any]:
        return self._get(WEB_URL + path, params, auth=False)

    def _paged(self, path: str, key: str, **params: Any) -> Iterator[dict[str, Any]]:
        page: int | None = 1
        while page:
            data = self._web(path, per_page=PAGE_SIZE, page=page, **params)
            yield from data[key]
            page = data.get("next_page")

    # -- endpoints ---------------------------------------------------------

    def search(self, query: str, page: int = 1) -> list[dict[str, Any]]:
        """Song hits for a text query (Genius has no artist-only search)."""
        data = self._public("/search", q=query, per_page=20, page=page)
        return [h["result"] for h in data["hits"]]

    def artist(self, artist_id: int) -> dict[str, Any]:
        return self._public(f"/artists/{artist_id}", text_format="plain")["artist"]

    def song(self, song_id: int) -> dict[str, Any]:
        return self._public(f"/songs/{song_id}", text_format="plain")["song"]

    def album(self, album_id: int) -> dict[str, Any]:
        return self._web(f"/albums/{album_id}")["album"]

    def artist_albums(self, artist_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        """Albums of an artist, newest first. limit=None means all of them."""
        albums: list[dict[str, Any]] = []
        for album in self._paged(f"/artists/{artist_id}/albums", "albums"):
            albums.append(album)
            if limit is not None and len(albums) >= limit:
                break
        return albums

    def album_tracks(self, album_id: int) -> list[dict[str, Any]]:
        """Tracklist entries: {"number", "disc_number", "song": {...}}."""
        return list(self._paged(f"/albums/{album_id}/tracks", "tracks"))


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
