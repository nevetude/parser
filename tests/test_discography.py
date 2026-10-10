import pytest
from sqlalchemy import func, select

from genius_parser.client import GeniusNotFound
from genius_parser.db import make_session_factory
from genius_parser.discography import DiscographyService
from genius_parser.models import Album, AlbumTrack, Artist, Song, SongCredit
from genius_parser.progress import Cancelled, Reporter


def brief(i, name):
    return {"id": i, "name": name, "url": f"u/{i}", "image_url": None}


def artist(i, name, **rels):
    return {**brief(i, name), "artist_relationships": [
        {"relationship_type": t, "artists": [brief(a, n) for a, n in v]} for t, v in rels.items()
    ]}


# Band(1) = Alice(2) + Bob(3).  Alice is also in Side Project(4); Side Project also has Carol(5) and
# Dan(6), and Carol is in Deep Group(7), which must NOT be fetched (too deep).
ARTISTS = {
    1: artist(1, "Band", members=[(2, "Alice"), (3, "Bob")]),
    2: artist(2, "Alice", member_of=[(1, "Band"), (4, "Side Project")]),
    3: artist(3, "Bob", member_of=[(1, "Band")]),
    4: artist(4, "Side Project", members=[(2, "Alice"), (5, "Carol"), (6, "Dan")]),
    5: artist(5, "Carol", member_of=[(7, "Deep Group")]),
    6: artist(6, "Dan"),
    7: artist(7, "Deep Group", members=[(5, "Carol"), (8, "Eve")]),
    9: artist(9, "Producer"),
}


def song(i, title):
    return {"id": i, "title": title, "full_title": title, "primary_artist": brief(1, "Band"),
            "primary_artists": [brief(1, "Band")], "featured_artists": [brief(2, "Alice")],
            "writer_artists": [], "producer_artists": [brief(9, "Producer")],
            "custom_performances": [{"label": "Guitar", "artists": [brief(3, "Bob")]}],
            "release_date_components": {"year": 2020, "month": 1, "day": 2}}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.albums = [{"id": 100 + n, "name": f"Album {n}", "primary_artists": [brief(1, "Band")]} for n in range(5)]

    def _log(self, *c):
        self.calls.append(c)

    def search(self, q, page=1):
        return [] if page > 1 else [{"primary_artist": brief(1, "Band")}, {"primary_artist": brief(1, "Band")}]

    def artist(self, i):
        self._log("artist", i)
        if i not in ARTISTS:
            raise GeniusNotFound(str(i))
        return ARTISTS[i]

    def song(self, i):
        self._log("song", i)
        return song(i, f"Song {i}")

    def album(self, i):
        self._log("album", i)
        return {"id": i, "name": f"Album {i - 100}", "primary_artists": [brief(1, "Band")],
                "release_date_components": {"year": 2020}}

    def artist_albums(self, i, limit=None):
        self._log("artist_albums", i, limit)
        return self.albums[:limit]

    def album_tracks(self, i):
        self._log("album_tracks", i)
        return [{"number": n, "disc_number": 1, "song": {"id": i * 10 + n, "title": f"S{n}"}} for n in (1, 2)]

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


@pytest.fixture
def env():
    client = FakeClient()
    sf = make_session_factory("sqlite://")
    return client, sf, DiscographyService(client, sf)


def ids(sf, model, *where):
    with sf() as s:
        return set(s.scalars(select(model.id).where(*where)))


def test_search_dedupes_artists(env):
    client, _, svc = env
    assert [a["id"] for a in svc.artists.search("band")] == [1]


def test_full_cycle_limit_and_tracks(env):
    client, sf, svc = env
    summary = svc.run(1, albums_limit=2)
    assert summary == {"albums": 2, "songs": 4, "artists": 4, "errors": 0}
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(Album).where(Album.tracks_loaded)) == 2
        assert s.scalar(select(func.count()).select_from(Song).where(Song.loaded)) == 4
        track = s.scalar(select(AlbumTrack).where(AlbumTrack.album_id == 100, AlbumTrack.number == 2))
        assert (track.song_id, track.disc_number) == (1002, 1)
        roles = {(c.role, c.detail) for c in s.scalars(select(SongCredit))}
        assert roles == {("primary", ""), ("featured", ""), ("producer", ""), ("performance", "Guitar")}


def test_default_is_20_and_none_means_all(env):
    client, _, svc = env
    svc.run(1)
    assert ("artist_albums", 1, 20) in client.calls
    svc.run(1, albums_limit=None)
    assert ("artist_albums", 1, None) in client.calls


def test_groups_flagged_and_expanded_one_level(env):
    client, sf, svc = env
    svc.run(1, albums_limit=1)
    with sf() as s:
        groups = set(s.scalars(select(Artist.id).where(Artist.is_group)))
        loaded = set(s.scalars(select(Artist.id).where(Artist.loaded)))
    # Alice's groups (Band, Side Project) and their members (Carol, Dan) are fetched in full
    assert {1, 2, 3, 4, 5, 6, 9} <= loaded
    assert {1, 4} <= groups
    # Carol belongs to Deep Group, but Carol was only a member (depth 1): Deep Group is not fetched
    assert 7 not in loaded and 8 not in loaded
    assert ("artist", 7) not in client.calls


def test_rerun_skips_everything_already_stored(env):
    client, _, svc = env
    svc.run(1, albums_limit=2)
    client.calls.clear()
    svc.run(1, albums_limit=2)
    assert [c for c in client.calls if c[0] != "artist_albums"] == []


def test_force_refetches(env):
    client, _, svc = env
    svc.run(1, albums_limit=1)
    client.calls.clear()
    svc.run(1, albums_limit=1, force=True)
    assert client.count("album") == 1 and client.count("song") == 2


def test_modules_work_alone(env):
    client, sf, svc = env
    svc.songs.ingest(555)
    assert client.calls == [("song", 555)]
    assert ids(sf, Song, Song.loaded) == {555}
    assert ids(sf, Album) == set()
    svc.artists.ingest(6, expand=False)
    assert ids(sf, Artist, Artist.loaded) == {6}


def test_missing_artist_is_skipped_not_fatal(env):
    client, _, svc = env
    ARTISTS_BACKUP = ARTISTS.pop(9)
    try:
        assert svc.run(1, albums_limit=1)["errors"] == 1
    finally:
        ARTISTS[9] = ARTISTS_BACKUP


def test_cancel(env):
    _, sf, svc = env

    class Stop(Reporter):
        def update(self, stage, done=0, total=0, message=""):
            if stage == "tracks":
                raise Cancelled()

    with pytest.raises(Cancelled):
        svc.run(1, albums_limit=3, reporter=Stop())
