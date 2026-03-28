"""
logger.py — Structured, rotating logger for the Movie Harvester bot.

Features:
  • INFO+ to console with concise formatting.
  • DEBUG+ to `harvester.log` with full timestamps (rotating, max 5 MB × 3 files).
  • Single `get_logger(name)` factory imported by every module.

Usage:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("Harvest cycle started.")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "harvester.log"
MAX_BYTES_PER_FILE = 5 * 1024 * 1024   # 5 MB
BACKUP_COUNT = 3

CONSOLE_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
FILE_FORMAT    = "%(asctime)s  %(levelname)-8s  %(name)s  [%(filename)s:%(lineno)d] — %(message)s"
DATE_FORMAT    = "%Y-%m-%d %H:%M:%S"

# ── Colour codes for console output (Windows-safe via ANSI) ─────────────────
_LEVEL_COLOURS = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Green
    "WARNING":  "\033[33m",   # Yellow
    "ERROR":    "\033[31m",   # Red
    "CRITICAL": "\033[1;31m", # Bold Red
}
_RESET = "\033[0m"


class _ColouredFormatter(logging.Formatter):
    """Apply ANSI colour codes to the levelname in console output."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        record.levelname = f"{colour}{record.levelname}{_RESET}"
        return super().format(record)


def _build_root_logger() -> None:
    """
    Configure the root logger exactly once (idempotent).
    Subsequent calls to `get_logger()` inherit these handlers automatically.
    """
    root = logging.getLogger()

    # Avoid adding duplicate handlers if this module is re-imported.
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # ── Console handler (INFO and above, coloured) ────────────────────────
    # Wrap stdout with a UTF-8 recoder so emoji / box-line chars don't crash
    # on Windows terminals that default to cp1252.
    import io
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout,
        encoding="utf-8",
        errors="replace",
        line_buffering=True,
    )
    console_handler = logging.StreamHandler(utf8_stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        _ColouredFormatter(fmt=CONSOLE_FORMAT, datefmt=DATE_FORMAT)
    )

    # ── Rotating file handler (DEBUG and above, plain text) ───────────────
    file_handler = RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=MAX_BYTES_PER_FILE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(fmt=FILE_FORMAT, datefmt=DATE_FORMAT)
    )

    root.addHandler(console_handler)
    root.addHandler(file_handler)


# Build once at import time.
_build_root_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger that inherits the root configuration.

    Args:
        name: Typically `__name__` from the calling module.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)
