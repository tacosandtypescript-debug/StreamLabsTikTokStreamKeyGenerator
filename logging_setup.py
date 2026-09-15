"""Logging configuration.

The packaged application has no console (``--windows-console-mode=disable``),
so the log file is the only way a user can hand over something useful for
diagnosis. Nothing that goes through this logger may contain a token, an
authorization code or a stream key.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

from config_store import APP_AUTHOR, APP_NAME

LOG_FILENAME = "app.log"
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_directory() -> Path:
    """Return the directory where the application writes its log file."""

    return Path(user_log_dir(APP_NAME, APP_AUTHOR))


def log_file_path() -> Path:
    """Return the full path of the application log file."""

    return log_directory() / LOG_FILENAME


def configure_logging(level: str = "WARNING") -> Path | None:
    """Configure logging and return the log file path, if it is writable.

    Returns ``None`` when the log file cannot be created, in which case only the
    console handler (if there is any console) remains active.
    """

    handlers: list[logging.Handler] = []
    file_path: Path | None = None

    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        candidate = log_file_path()
        handlers.append(
            RotatingFileHandler(
                candidate,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
        )
        file_path = candidate
    except OSError:
        file_path = None

    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    if not handlers:
        # A windowed build may have neither a writable log file nor a console.
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=level.upper(),
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
    return file_path
