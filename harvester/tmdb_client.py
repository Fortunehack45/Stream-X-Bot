"""
tmdb_client.py — TMDB metadata enrichment client for the Movie Harvester bot.

Since scraper.py now harvests directly from the TMDB API, RawMovieEntry objects
arrive pre-populated with TMDB metadata (tmdb_id, poster_url, rating, overview).

This module's enrich() method:
  1. If the RawMovieEntry already has a tmdb_id → converts directly to MovieRecord
     (no additional API call needed).
  2. If no tmdb_id is set (future extension / manual entries) → falls back to
     TMDB title search with year-proximity scoring.

Usage:
    from tmdb_client import TMDBClient
    from scraper import RawMovieEntry

    client = TMDBClient()
    record = client.enrich(raw_entry)
"""

from __future__ import annotations

import re
from typing import Optional

import requests # type: ignore

from config import settings # type: ignore
from database import MovieRecord # type: ignore
from logger import get_logger # type: ignore

log = get_logger(__name__)

# Base URL for constructing full poster image URLs (TMDB standard).
_TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
_TMDB_API_BASE       = "https://api.themoviedb.org/3"

# Regex to extract a 4-digit year from a movie title (e.g. "Inception (2010)").
_TITLE_YEAR_PATTERN = re.compile(r"\((\d{4})\)\s*$")


def _clean_title(raw_title: str) -> tuple[str, Optional[int]]:
    """
    Strip an embedded year from a title string.

    Returns:
        (clean_title, year_hint) where year_hint is None if no year was found.
    """
    match = _TITLE_YEAR_PATTERN.search(raw_title)
    if match:
        year_hint = int(match.group(1))
        clean = raw_title[: match.start()].strip() # type: ignore
        return clean, year_hint
    return raw_title.strip(), None


def _score_candidate(candidate: dict, year_hint: Optional[int]) -> float:
    """
    Score a TMDB search result by popularity + year proximity.
    Used only for fallback title-search mode.
    """
    popularity = float(candidate.get("popularity", 0))
    candidate_year: Optional[int] = None

    release_date = candidate.get("release_date", "") or candidate.get("first_air_date", "")
    if release_date and len(release_date) >= 4:
        try:
            candidate_year = int(release_date[:4])
        except ValueError:
            pass

    year_bonus = 0.0
    if year_hint and candidate_year:
        year_diff = abs(year_hint - candidate_year)
        if year_diff == 0:
            year_bonus = 500.0
        elif year_diff <= 2:
            year_bonus = 100.0 / (year_diff + 1)

    return popularity + year_bonus


class TMDBClient:
    """
    Handles conversion of RawMovieEntry → MovieRecord.

    Primary path (fast): RawMovieEntry already has tmdb_id → no API call.
    Fallback path: title-search via TMDB API for manually-added entries.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {settings.tmdb_api_key}",
            "Accept":        "application/json",
        })
        log.info("TMDBClient initialised.")

    def enrich(self, raw_entry) -> Optional[MovieRecord]:
        """
        Convert a RawMovieEntry to a fully-enriched MovieRecord.

        Fast path: if raw_entry.tmdb_id is set (TMDB-direct harvest), build
        the record directly with no additional API calls.

        Fallback path: title search + best-match scoring.

        Args:
            raw_entry: A RawMovieEntry from scraper.py.

        Returns:
            A populated MovieRecord, or None if enrichment fails.
        """
        # ── Fast path: entry already has TMDB data ────────────────────────────
        if getattr(raw_entry, "tmdb_id", None):
            log.debug(
                "Fast-path enrich: %r (TMDB ID: %s)", raw_entry.title, raw_entry.tmdb_id
            )
            return MovieRecord(
                title=raw_entry.title,
                source_url=raw_entry.source_url,
                embed_url=getattr(raw_entry, "embed_url", None),
                tmdb_id=raw_entry.tmdb_id,
                poster_url=raw_entry.poster_url,
                rating=raw_entry.rating,
                overview=raw_entry.overview,
                genres=getattr(raw_entry, "genres", []),
                director=getattr(raw_entry, "director", None),
                cast_members=getattr(raw_entry, "cast_members", []),
                producers=getattr(raw_entry, "producers", []),
                related_tmdb_ids=getattr(raw_entry, "related_tmdb_ids", []),
            )

        # ── Fallback path: title search ───────────────────────────────────────
        clean_title, year_hint = _clean_title(raw_entry.title)
        log.debug("Fallback TMDB search for %r (year hint: %s)…", clean_title, year_hint)

        try:
            params   = {"query": clean_title, "language": "en-US", "page": 1}
            response = self._session.get(
                f"{_TMDB_API_BASE}/search/multi",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            results  = response.json().get("results", [])
        except Exception as exc:
            log.error("TMDB search failed for %r: %s", clean_title, exc)
            return None

        if not results:
            log.warning("No TMDB results for %r — skipping.", clean_title)
            return None

        best = max(results, key=lambda c: _score_candidate(c, year_hint))

        tmdb_id    = best.get("id")
        title      = best.get("title") or best.get("name") or clean_title
        raw_poster = best.get("poster_path")
        poster_url = f"{_TMDB_IMAGE_BASE_URL}{raw_poster}" if raw_poster else None
        raw_rating = best.get("vote_average")
        rating     = round(float(raw_rating), 1) if raw_rating is not None else None # type: ignore
        overview   = best.get("overview") or None

        log.info(
            "Matched %r → TMDB ID %s | %r | Rating: %s",
            clean_title, tmdb_id, title, rating,
        )

        return MovieRecord(
            title=title,
            source_url=raw_entry.source_url,
            embed_url=getattr(raw_entry, "embed_url", None),
            tmdb_id=tmdb_id,
            poster_url=poster_url,
            rating=rating,
            overview=overview,
        )
