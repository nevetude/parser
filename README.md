# Genius Parser

Парсер дискографии артиста из Genius в SQLite (Postgres — сменой `DATABASE_URL`) + сайт для управления.

```bash
uv run uvicorn main:app --reload     # http://localhost:8000
uv run pytest
```

`.env`: `GENIUS_ACCESS_TOKEN`, `DATABASE_URL` (по умолчанию `sqlite:///music.db`), `GENIUS_MIN_INTERVAL`, `DEFAULT_ALBUMS_LIMIT` (20).

## Цикл «Дискография»

1. профиль артиста; если у него есть `member_of` — эта группа и все её участники (профили через `/artists/{id}`); если он сам группа — его участники. Глубже не идём;
2. N альбомов (по умолчанию 20, `null` = все), новые первыми;
3. каждый альбом с треклистом (номера треков и дисков) и каждый трек целиком;
4. все артисты из credits (основные, featured, авторы, продюсеры, performances) — полный профиль + пункт 1.

Группа = непустое `members` в `artist_relationships` (`artist.is_group`). Уже загруженное пропускается, `force` перезапрашивает всё. Полный ответ Genius хранится в колонке `raw`.

## Модули (`genius_parser/`)

Каждый работает отдельно: `fetch` — живой запрос без записи в БД, `ingest` — сохранить.

| Модуль | Что делает |
|---|---|
| `artists.ArtistService` | `search(name)`, `fetch(id)`, `ingest(id, expand=True)` |
| `songs.SongService` | `fetch(id)`, `ingest(id)` |
| `albums.AlbumService` | `list_for_artist(id, limit)`, `fetch(id)`, `ingest(id, with_songs=True)` |
| `discography.DiscographyService` | `run(artist_id, albums_limit=20, force=False, reporter=…)` |

Тот же набор есть в HTTP: `GET /api/{artists,songs,albums}/{id}`, `POST /api/{artists,songs,albums}/{id}/ingest`, `POST /api/discography` (фоновая задача), `GET /api/jobs`, `POST /api/jobs/{id}/cancel`, `GET /api/db/...`.

## Источники

Артисты, песни, поиск — `api.genius.com` с токеном. Список альбомов артиста, альбом и треклист — неофициальный `genius.com/api` (без токена; с токеном он отвечает 403). Он недокументирован и может измениться.
