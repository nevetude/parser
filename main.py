from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from genius_parser import config
from genius_parser.client import GeniusClient, GeniusError, GeniusNotFound
from genius_parser.db import make_session_factory
from genius_parser.discography import DiscographyService
from genius_parser.jobs import JobManager
from genius_parser.queries import Queries

jobs = JobManager()


@lru_cache
def get_app_state():
    sf = make_session_factory(config.DATABASE_URL)
    client = GeniusClient(config.TOKEN, min_interval=config.MIN_INTERVAL)
    return DiscographyService(client, sf), Queries(sf)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_app_state()
    yield


app = FastAPI(lifespan=lifespan)


def svc() -> DiscographyService:
    return get_app_state()[0]


def q() -> Queries:
    return get_app_state()[1]


@app.exception_handler(GeniusNotFound)
async def _not_found(_, exc):
    return JSONResponse({"detail": "Not found on Genius"}, status_code=404)


@app.exception_handler(GeniusError)
async def _genius_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


# -- live lookups (nothing stored) -------------------------------------------

@app.get("/api/search/artists")
def search_artists(name: str = Query(min_length=1)):
    return svc().artists.search(name)


@app.get("/api/artists/{artist_id}")
def get_artist(artist_id: int):
    return svc().artists.fetch(artist_id)


@app.get("/api/songs/{song_id}")
def get_song(song_id: int):
    return svc().songs.fetch(song_id)


@app.get("/api/albums/{album_id}")
def get_album(album_id: int):
    return svc().albums.fetch(album_id)


# -- ingest: each module on its own ---------------------------------------------

@app.post("/api/artists/{artist_id}/ingest")
def ingest_artist(artist_id: int, expand: bool = True, force: bool = False):
    p = svc().artists.ingest(artist_id, expand=expand, force=force)
    return {"id": p["id"], "name": p["name"]}


@app.post("/api/songs/{song_id}/ingest")
def ingest_song(song_id: int, force: bool = False):
    p = svc().songs.ingest(song_id, force=force)
    return {"id": p["id"], "title": p["title"]}


@app.post("/api/albums/{album_id}/ingest")
def ingest_album(album_id: int, with_songs: bool = True, force: bool = False):
    ids = svc().albums.ingest(album_id, with_songs=with_songs, force=force)
    return {"id": album_id, "tracks": len(ids)}


# -- full discography: background job ----------------------------------------------

class DiscographyRequest(BaseModel):
    artist_id: int
    albums_limit: int | None = Field(config.DEFAULT_ALBUMS_LIMIT, ge=1)  # explicit null = all albums
    force: bool = False


@app.post("/api/discography")
def start_discography(req: DiscographyRequest):
    params = req.model_dump()
    if running := jobs.active_for("discography", params):
        return running.to_dict()
    job = jobs.start(
        "discography", params, f"Артист {req.artist_id}",
        lambda rep: svc().run(req.artist_id, albums_limit=req.albums_limit, force=req.force, reporter=rep),
    )
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs():
    return [j.to_dict() for j in jobs.list()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return {"cancelled": jobs.cancel(job_id)}


# -- stored data ------------------------------------------------------------------------

@app.get("/api/db/stats")
def db_stats():
    return q().stats()


@app.get("/api/db/artists")
def db_artists(q_: str = Query("", alias="q"), groups_only: bool = False):
    return q().list_artists(q_, groups_only)


def _or_404(value):
    if value is None:
        raise HTTPException(404, "Not in the database")
    return value


@app.get("/api/db/artists/{artist_id}")
def db_artist(artist_id: int):
    return _or_404(q().artist(artist_id))


@app.get("/api/db/albums/{album_id}")
def db_album(album_id: int):
    return _or_404(q().album(album_id))


@app.get("/api/db/songs/{song_id}")
def db_song(song_id: int):
    return _or_404(q().song(song_id))


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
