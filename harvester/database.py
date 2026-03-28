"""
database.py — PostgreSQL persistence layer for the Movie Harvester bot.

Responsibilities:
  • Bootstrap the `movies` schema on first run.
  • Upsert enriched MovieRecord objects (no duplicates via TMDB ID / source URL).
  • Expose a thread-safe context manager for connections.

Usage:
    from database import DatabaseManager
    db = DatabaseManager()
    db.bootstrap()
    db.upsert(movie_record)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import psycopg2 # type: ignore
import psycopg2.extras # type: ignore
from psycopg2.extensions import connection as PgConnection # type: ignore

from config import settings # type: ignore
from logger import get_logger # type: ignore

log = get_logger(__name__)

# ── DDL ─────────────────────────────────────────────────────────────────────

_CREATE_MOVIES_TABLE = """
CREATE TABLE IF NOT EXISTS movies (
    id               SERIAL PRIMARY KEY,
    tmdb_id          INTEGER  UNIQUE,
    title            TEXT     NOT NULL,
    media_type       TEXT     DEFAULT 'movie',
    source_url       TEXT     UNIQUE NOT NULL,
    embed_url        TEXT,
    poster_url       TEXT,
    backdrop_url     TEXT,
    rating           NUMERIC(3,1),
    release_date     TEXT,
    popularity       NUMERIC,
    overview         TEXT,
    genres           TEXT[],
    director         TEXT,
    cast_members     TEXT[],
    producers        TEXT[],
    related_tmdb_ids INTEGER[],
    harvested_at     TIMESTAMPTZ DEFAULT NOW()
);
"""

_UPSERT_MOVIE = """
INSERT INTO movies
    (tmdb_id, title, media_type, source_url, embed_url, poster_url, backdrop_url,
     rating, release_date, popularity, overview, genres, director, 
     cast_members, producers, related_tmdb_ids, harvested_at)
VALUES
    (%(tmdb_id)s, %(title)s, %(media_type)s, %(source_url)s, %(embed_url)s, 
     %(poster_url)s, %(backdrop_url)s, %(rating)s, %(release_date)s, 
     %(popularity)s, %(overview)s, %(genres)s, %(director)s,
     %(cast_members)s, %(producers)s, %(related_tmdb_ids)s, %(harvested_at)s)
ON CONFLICT (source_url) DO UPDATE SET
    tmdb_id          = EXCLUDED.tmdb_id,
    title            = EXCLUDED.title,
    media_type       = EXCLUDED.media_type,
    embed_url        = EXCLUDED.embed_url,
    poster_url       = EXCLUDED.poster_url,
    backdrop_url     = EXCLUDED.backdrop_url,
    rating           = EXCLUDED.rating,
    release_date     = EXCLUDED.release_date,
    popularity       = EXCLUDED.popularity,
    overview         = EXCLUDED.overview,
    genres           = EXCLUDED.genres,
    director         = EXCLUDED.director,
    cast_members     = EXCLUDED.cast_members,
    producers        = EXCLUDED.producers,
    related_tmdb_ids = EXCLUDED.related_tmdb_ids,
    harvested_at     = EXCLUDED.harvested_at;
"""


# ── Data Contract ────────────────────────────────────────────────────────────

@dataclass
class MovieRecord:
    """
    Fully-enriched movie record ready for database persistence.
    Produced by TMDBClient.enrich() and consumed by DatabaseManager.upsert().
    """
    title:            str
    source_url:       str
    media_type:       str             = "movie"
    embed_url:        Optional[str]   = None
    tmdb_id:          Optional[int]   = None
    poster_url:       Optional[str]   = None
    backdrop_url:     Optional[str]   = None
    rating:           Optional[float] = None
    release_date:     Optional[str]   = None
    popularity:       Optional[float] = None
    overview:         Optional[str]   = None
    genres:           list[str]       = field(default_factory=list)
    director:         Optional[str]   = None
    cast_members:     list[str]       = field(default_factory=list)
    producers:        list[str]       = field(default_factory=list)
    related_tmdb_ids: list[int]       = field(default_factory=list)
    harvested_at:     datetime        = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Manager ──────────────────────────────────────────────────────────────────

class DatabaseManager:
    """
    Manages PostgreSQL connectivity and all movie persistence operations.

    Each public method opens a fresh connection from scratch, so this class
    is safe to use across threads without a shared connection pool.
    """

    def __init__(self) -> None:
        self._dsn = settings.db_dsn

    @contextlib.contextmanager
    def _get_connection(self):
        """Yield a psycopg2 connection and auto-commit or rollback on exit."""
        # Supavisor (Supabase Pooler) can be picky about URI strings.
        # We'll use individual parameters for maximum reliability.
        conn: PgConnection = psycopg2.connect(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            sslmode="require",
            connect_timeout=15
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def bootstrap(self) -> None:
        """
        Create the `movies` table if it does not already exist.
        Safe to call on every startup — it is fully idempotent.
        """
        log.info("Bootstrapping database schema…")
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_CREATE_MOVIES_TABLE)
        log.info("Schema is ready.")

    def upsert(self, record: MovieRecord) -> None:
        """
        Insert a MovieRecord or silently update it if source_url already exists.

        Args:
            record: A fully-populated MovieRecord dataclass instance.
        """
        log.debug(
            "Upserting record — title=%r  tmdb_id=%s  source_url=%s",
            record.title,
            record.tmdb_id,
            record.source_url,
        )
        params = {
            "tmdb_id":          record.tmdb_id,
            "title":            record.title,
            "media_type":       record.media_type,
            "source_url":       record.source_url,
            "embed_url":        record.embed_url,
            "poster_url":       record.poster_url,
            "backdrop_url":     record.backdrop_url,
            "rating":           record.rating,
            "release_date":     record.release_date,
            "popularity":       record.popularity,
            "overview":         record.overview,
            "genres":           record.genres,
            "director":         record.director,
            "cast_members":     record.cast_members,
            "producers":        record.producers,
            "related_tmdb_ids": record.related_tmdb_ids,
            "harvested_at":     record.harvested_at,
        }
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_UPSERT_MOVIE, params)
        log.info("Persisted: %r (TMDB ID: %s)", record.title, record.tmdb_id)

    def count_movies(self) -> int:
        """Return the total number of rows in the movies table (useful for health checks)."""
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM movies;")
                result = cursor.fetchone()
                return result[0] if result else 0
