import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOKEN = os.environ.get("GENIUS_ACCESS_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///music.db")
MIN_INTERVAL = float(os.environ.get("GENIUS_MIN_INTERVAL", "0.2"))  # pause between requests, s
DEFAULT_ALBUMS_LIMIT = int(os.environ.get("DEFAULT_ALBUMS_LIMIT", "20"))
