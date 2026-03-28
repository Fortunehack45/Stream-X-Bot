"""
scraper.py — TMDB API-direct harvester for the Movie Harvester bot.

Strategy:
  StreamX (https://stream-x-weld.vercel.app) is a React SPA that renders
  content dynamically from TMDB. DOM scraping is not viable because:
    1. All content is rendered client-side via JavaScript.
    2. The CSS is utility-only Tailwind v4 — no semantic class names exist.

  Instead, we harvest data DIRECTLY from TMDB's API:
    - /movie/popular  → popular movies
    - /tv/popular     → popular TV series
    - /movie/top_rated, /movie/upcoming, /tv/top_rated (configurable)

  The source_url is constructed as the canonical StreamX page for each item,
  preserving the original requirement of linking entries back to the platform.

Exponential Backoff:
  The @retry_with_backoff decorator is applied to every TMDB API call.
  It doubles the wait time on each failure and adds ±25% jitter.

Usage:
    from scraper import MovieScraper
    scraper = MovieScraper()
    raw_entries = scraper.harvest()
"""

from __future__ import annotations

import concurrent.futures
import functools
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar

import requests # type: ignore

from config import settings # type: ignore
from logger import get_logger # type: ignore

log = get_logger(__name__)
T = TypeVar("T")

# ── TMDB API Configuration ────────────────────────────────────────────────────

_TMDB_API_BASE    = "https://api.themoviedb.org/3"
_TMDB_IMAGE_BASE  = "https://image.tmdb.org/t/p/w500"

# StreamX base URL — used to construct canonical source URLs per title.
_STREAMX_BASE_URL = "https://stream-x-weld.vercel.app"

# TMDB API endpoints to harvest from on each cycle.
# Each entry: (endpoint_path, media_type, label)
_HARVEST_ENDPOINTS = [
    ("/movie/popular",   "movie",  "Popular Movies"),
    ("/tv/popular",      "series", "Popular Series"),
    ("/movie/top_rated", "movie",  "Top Rated Movies"),
    ("/tv/top_rated",    "series", "Top Rated Series"),
    ("/movie/upcoming",  "movie",  "Upcoming Movies"),
]

# Number of pages to fetch per endpoint per cycle (each page = 20 results).
_PAGES_PER_ENDPOINT = settings.pages_per_endpoint


# ── Data Contract ─────────────────────────────────────────────────────────────

@dataclass
class RawMovieEntry:
    """
    Minimally-processed content entry returned by the harvester.
    Passed directly to TMDBClient.enrich() (or used as-is for pre-enriched data).
    """
    title:            str
    source_url:       str
    embed_url:        Optional[str]   = None
    tmdb_id:          Optional[int]   = None
    poster_url:       Optional[str]   = None
    rating:           Optional[float] = None
    overview:         Optional[str]   = None
    media_type:       str             = "movie"
    genres:           list[str]       = field(default_factory=list)
    director:         Optional[str]   = None
    cast_members:     list[str]       = field(default_factory=list)
    producers:        list[str]       = field(default_factory=list)
    related_tmdb_ids: list[int]       = field(default_factory=list)


# ── Retry Decorator ───────────────────────────────────────────────────────────

def retry_with_backoff(
    max_attempts: int | None = None,
    base_delay_seconds: float | None = None,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator factory that retries a function with exponential backoff + jitter.

    Strategy:
      • Attempt 1: immediate.
      • Attempt 2: wait base_delay * 2¹ ± jitter.
      • Attempt n: wait base_delay * 2^(n-1) ± jitter (capped at 120 s).

    Args:
        max_attempts:        Maximum attempts before re-raising. Defaults to
                             settings.max_retry_attempts.
        base_delay_seconds:  Seed delay in seconds. Defaults to
                             settings.retry_base_delay_seconds.
        exceptions:          Exception types to catch and retry on.
    """
    _max_attempts = max_attempts or settings.max_retry_attempts
    _base_delay   = base_delay_seconds or settings.retry_base_delay_seconds

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None
            for attempt in range(1, _max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt == _max_attempts:
                        log.error(
                            "All %d attempts exhausted for %s — final error: %s",
                            _max_attempts,
                            func.__name__,
                            exc,
                        )
                        break

                    raw_delay = _base_delay * (2 ** (attempt - 1))
                    jitter    = random.uniform(0, raw_delay * 0.25)
                    wait      = min(raw_delay + jitter, 120.0)

                    log.warning(
                        "Attempt %d/%d failed for %s: %s — retrying in %.1f s…",
                        attempt,
                        _max_attempts,
                        func.__name__,
                        exc,
                        wait,
                    )
                    time.sleep(wait)

            if last_exception:
                raise RuntimeError(
                    f"{func.__name__} failed after {_max_attempts} attempts."
                ) from last_exception
            raise RuntimeError("Unknown error in retry wrapper")

        return wrapper # type: ignore
    return decorator # type: ignore


# ── TMDB API Client ───────────────────────────────────────────────────────────

class MovieScraper:
    """
    TMDB API harvester that fetches popular/top-rated movies and series,
    constructs StreamX canonical URLs, and returns RawMovieEntry objects.

    Lifecycle:
        scraper = MovieScraper()
        entries = scraper.harvest()

    Or as a context manager (for API compatibility with main.py):
        with MovieScraper() as scraper:
            entries = scraper.harvest()
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {settings.tmdb_api_key}",
            "Accept":        "application/json",
            "User-Agent":    "MovieHarvesterBot/1.0",
        })
        log.info("MovieScraper (TMDB-direct mode) initialised.")

    @retry_with_backoff(
        exceptions=(requests.RequestException, ConnectionError, TimeoutError),
    )
    def _fetch_page(self, endpoint: str, page: int = 1) -> dict:
        """
        Fetch a single paginated page from the TMDB API.

        Args:
            endpoint: TMDB API path (e.g. "/movie/popular").
            page:     Page number (1-based).

        Returns:
            Parsed JSON response dict.

        Raises:
            requests.HTTPError: On 4xx/5xx responses after retries.
        """
        url    = f"{_TMDB_API_BASE}{endpoint}"
        params = {"language": "en-US", "page": page}

        log.debug("GET %s (page %d)…", url, page)
        response = self._session.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    @retry_with_backoff(
        exceptions=(requests.RequestException, ConnectionError, TimeoutError),
    )
    def _fetch_details(self, tmdb_id: int, media_type: str) -> dict | None:
        """
        Fetch deep details for a single item (cast, crew, genres, recommendations).
        """
        endpoint = f"/{media_type}/{tmdb_id}"
        url = f"{_TMDB_API_BASE}{endpoint}"
        params = {
            "language": "en-US",
            "append_to_response": "credits,recommendations"
        }
        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            # If 404, just ignore it.
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def _parse_results(
        self,
        results: list[dict],
        media_type: str,
    ) -> list[RawMovieEntry]:
        """
        Concurrently fetch deep metadata for a batch of TMDB IDs and build RawMovieEntry objects.
        """
        entries: list[RawMovieEntry] = []
        valid_ids = [r.get("id") for r in results if r.get("id")]

        # Fetch deep details concurrently (TMDB allows 50 req/sec, ThreadPool limits to 10 for safety)
        details_map = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {
                executor.submit(self._fetch_details, t_id, media_type): t_id
                for t_id in valid_ids
            }
            for future in concurrent.futures.as_completed(future_to_id):
                t_id = future_to_id[future]
                try:
                    data = future.result()
                    if data:
                        details_map[t_id] = data
                except Exception as exc:
                    log.error("Deep fetch failed for TMDB ID %s: %s", t_id, exc)

        for item in results:
            tmdb_id = item.get("id")
            if not tmdb_id or tmdb_id not in details_map:
                continue

            details = details_map[tmdb_id]

            # Title fallback
            title = details.get("title") or details.get("name") or ""
            if not title:
                continue

            # StreamX canonical URL
            url_path = "movies" if media_type == "movie" else "series"
            source_url = f"{_STREAMX_BASE_URL}/{url_path}/{tmdb_id}"

            # Poster & Rating
            raw_poster = details.get("poster_path")
            poster_url = f"{_TMDB_IMAGE_BASE}{raw_poster}" if raw_poster else None
            raw_rating = details.get("vote_average")
            rating = round(float(raw_rating), 1) if raw_rating is not None else None # type: ignore

            # Deep Metadata Extraction
            genres = [g.get("name") for g in details.get("genres", []) if g.get("name")]
            
            credits = details.get("credits", {})
            cast = [c.get("name") for c in credits.get("cast", [])[:5]]  # Top 5 cast members
            
            crew = credits.get("crew", [])
            director = next((c.get("name") for c in crew if c.get("job") == "Director"), None)
            producers = [c.get("name") for c in crew if c.get("job") == "Producer"]

            recommendations = details.get("recommendations", {}).get("results", [])
            related_ids = [r.get("id") for r in recommendations[:5]]  # Top 5 related

            entries.append(
                RawMovieEntry(
                    title=title,
                    source_url=source_url,
                    embed_url=None,
                    tmdb_id=tmdb_id,
                    poster_url=poster_url,
                    rating=rating,
                    overview=details.get("overview") or None,
                    media_type=media_type,
                    genres=genres,
                    director=director,
                    cast_members=cast,
                    producers=producers,
                    related_tmdb_ids=related_ids,
                )
            )

        return entries

    def harvest(self, url: str | None = None) -> list[RawMovieEntry]:
        """
        Execute a full harvest across all configured TMDB endpoints.

        Args:
            url: Unused parameter kept for API compatibility with main.py.
                 The TMDB endpoints are defined in _HARVEST_ENDPOINTS.

        Returns:
            Deduplicated list of RawMovieEntry objects across all endpoints.
        """
        all_entries: list[RawMovieEntry] = []
        seen_tmdb_ids: set[int]          = set()

        for endpoint, media_type, label in _HARVEST_ENDPOINTS:
            log.info("Harvesting endpoint: %s (%s)…", label, endpoint)
            endpoint_count: int = 0

            for page in range(1, _PAGES_PER_ENDPOINT + 1):
                try:
                    data    = self._fetch_page(endpoint, page=page)
                    results = data.get("results", [])
                    entries = self._parse_results(results, media_type)

                    for entry in entries:
                        t_id = entry.tmdb_id
                        if t_id and t_id not in seen_tmdb_ids:
                            seen_tmdb_ids.add(t_id)
                            all_entries.append(entry)
                            endpoint_count = endpoint_count + 1 # type: ignore

                except Exception as exc:
                    log.error(
                        "Failed to fetch %s page %d: %s — continuing.",
                        endpoint,
                        page,
                        exc,
                    )

            log.info("  → %d unique entries from %s.", endpoint_count, label)

        log.info(
            "Harvest complete — %d total unique entries across all endpoints.",
            len(all_entries),
        )
        return all_entries

    def save_screenshot(self, file_path: str) -> None:
        """No-op — kept for API compatibility. TMDB mode has no browser."""
        log.debug("save_screenshot() called in TMDB-direct mode — no-op.")

    def quit(self) -> None:
        """Close the requests session."""
        self._session.close()
        log.debug("MovieScraper HTTP session closed.")

    def __enter__(self) -> "MovieScraper":
        return self

    def __exit__(self, *_) -> None:
        self.quit()
