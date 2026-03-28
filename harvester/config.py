"""
config.py — Centralised environment variable loader.

All modules import from here so secrets live in exactly one place.
Usage:
    from config import settings
    print(settings.tmdb_api_key)
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv # type: ignore

# Load .env from the same directory as this file (or parent directories).
load_dotenv()


def _require(key: str) -> str:
    """Return the value of a mandatory env var or raise a descriptive error."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing. "
            f"Copy .env.example → .env and fill in your values."
        )
    return value


def _optional(key: str, default: str) -> str:
    """Return the value of an optional env var, falling back to `default`."""
    return os.getenv(key, default)


@dataclass(frozen=True)
class Settings:
    # ── TMDB ─────────────────────────────────────────────────────────────────
    tmdb_api_key: str

    # ── Scraper ──────────────────────────────────────────────────────────────
    target_url: str
    pages_per_endpoint: int
    page_load_wait_seconds: int
    max_retry_attempts: int
    retry_base_delay_seconds: float

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    database_url: Optional[str] = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "movie_harvester"
    db_user: str = "harvester"
    db_password: Optional[str] = None

    # ── Scheduler ────────────────────────────────────────────────────────────
    scrape_interval_hours: int = 3

    @property
    def db_dsn(self) -> str:
        """Return a psycopg2-compatible DSN connection string."""
        if self.database_url:
            return str(self.database_url)
            
        if not self.db_password:
            raise EnvironmentError("Either DATABASE_URL or DB_PASSWORD must be provided.")
            
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password={self.db_password}"
        )


# Singleton loaded once at import time. All modules reference this object.
settings = Settings(
    tmdb_api_key=_require("TMDB_API_KEY"),
    target_url=_require("TARGET_URL"),
    pages_per_endpoint=int(_optional("PAGES_PER_ENDPOINT", "500")),
    page_load_wait_seconds=int(_optional("PAGE_LOAD_WAIT_SECONDS", "8")),
    max_retry_attempts=int(_optional("MAX_RETRY_ATTEMPTS", "5")),
    retry_base_delay_seconds=float(_optional("RETRY_BASE_DELAY_SECONDS", "2")),
    database_url=_optional("DATABASE_URL", ""),
    db_host=_optional("DB_HOST", "localhost"),
    db_port=int(_optional("DB_PORT", "5432")),
    db_name=_optional("DB_NAME", "movie_harvester"),
    db_user=_optional("DB_USER", "harvester"),
    db_password=_optional("DB_PASSWORD", ""),
    scrape_interval_hours=int(_optional("SCRAPE_INTERVAL_HOURS", "3")),
)
