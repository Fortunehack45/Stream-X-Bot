"""
main.py — Orchestration layer for the Movie Harvester bot.

This is the entry point. It wires together the Scraper, TMDB Client, and
Database Manager into a single repeating harvest cycle, then hands scheduling
control to the `schedule` library for 24/7 operation.

Usage:
    # Run continuously (24/7):
    python main.py

    # Single dry-run cycle (exits after one harvest):
    python main.py --dry-run
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

import schedule

from config import settings
from database import DatabaseManager
from logger import get_logger
from scraper import MovieScraper
from tmdb_client import TMDBClient

log = get_logger(__name__)


# ── Harvester Bot ─────────────────────────────────────────────────────────────

class HarvesterBot:
    """
    Coordinates the full movie harvest pipeline in a single cycle.

    Pipeline:
        Scraper → RawMovieEntry list
            → TMDBClient.enrich()  → MovieRecord
                → DatabaseManager.upsert() → PostgreSQL

    Each component is instantiated once per HarvesterBot lifetime and reused
    across cycles to avoid repeated browser startup / API initialisation costs.
    """

    def __init__(self) -> None:
        log.info("═" * 60)
        log.info("  🎬  Movie Harvester Bot — Initialising")
        log.info("═" * 60)

        self._db     = DatabaseManager()
        self._tmdb   = TMDBClient()
        self._db.bootstrap()

        log.info(
            "Bot ready. Target: %s | Schedule: every %d hour(s).",
            settings.target_url,
            settings.scrape_interval_hours,
        )

    # ── Cycle Logic ───────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        """
        Execute a complete harvest cycle:
          1. Spin up headless browser.
          2. Scrape TARGET_URL for raw movie entries.
          3. Enrich each entry via TMDB.
          4. Upsert each enriched record into PostgreSQL.
          5. Close the browser.

        Exceptions at the per-entry level are caught and logged so a single
        bad entry never aborts the entire cycle.
        """
        log.info("─" * 60)
        log.info("Harvest cycle starting…")

        new_count    = 0
        failed_count = 0

        with MovieScraper() as scraper:
            raw_entries = scraper.harvest()

            if not raw_entries:
                log.warning("No movie entries found on this cycle.")
                return

            log.info("Harvested %d raw entries. Beginning enrichment…", len(raw_entries))

            for raw_entry in raw_entries:
                try:
                    enriched_record = self._tmdb.enrich(raw_entry)

                    if enriched_record is None:
                        log.warning(
                            "Skipping %r — no TMDB match found.", raw_entry.title
                        )
                        failed_count += 1
                        continue

                    self._db.upsert(enriched_record)
                    new_count += 1

                except Exception as exc:
                    # Log the failure but continue processing remaining entries.
                    log.error(
                        "Failed to process entry %r: %s", raw_entry.title, exc,
                        exc_info=True,
                    )
                    failed_count += 1

        total_in_db = self._db.count_movies()
        log.info(
            "Cycle complete — processed: %d | skipped/failed: %d | total in DB: %d.",
            new_count,
            failed_count,
            total_in_db,
        )
        log.info("─" * 60)


# ── Signal Handling ───────────────────────────────────────────────────────────

def _handle_shutdown(signum, _frame) -> None:
    """Gracefully exit on SIGINT (Ctrl+C) or SIGTERM."""
    log.info("Shutdown signal received (%s). Goodbye.", signal.Signals(signum).name)
    sys.exit(0)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Movie Harvester Bot — scrape, enrich, and persist movie data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run exactly one harvest cycle and exit (no scheduler loop).",
    )
    args = parser.parse_args()

    # Register graceful shutdown handlers.
    signal.signal(signal.SIGINT,  _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    bot = HarvesterBot()

    if args.dry_run:
        log.info("DRY RUN MODE — executing one cycle only.")
        bot.run_cycle()
        log.info("Dry run complete. Exiting.")
        return

    # ── 24/7 Scheduler Loop ───────────────────────────────────────────────────
    interval = settings.scrape_interval_hours
    log.info("Scheduler active — harvest will run every %d hour(s).", interval)

    # Run immediately on startup so we don't wait for the first interval.
    bot.run_cycle()

    schedule.every(interval).hours.do(bot.run_cycle)

    while True:
        schedule.run_pending()
        time.sleep(30)   # Poll every 30 seconds — negligible CPU overhead.


if __name__ == "__main__":
    main()
