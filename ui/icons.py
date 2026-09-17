"""Locating the artwork that ships with the application.

A Nuitka ``--standalone`` build copies the assets next to the executable, while
a source checkout keeps them in the repository root, so both places are tried.
Nothing here may raise: a missing icon is cosmetic.
"""

from __future__ import annotations

import logging
import platform
import sys
from pathlib import Path
from typing import Any

from runtime import is_frozen

LOGGER = logging.getLogger(__name__)

ASSETS_DIRECTORY_NAME = "assets"
DEFAULT_ICON_FILE = "icon.png"
_PLATFORM_ICON_FILES = {
    "Windows": "icon.ico",
    "Darwin": "icon.icns",
}


def assets_directory() -> Path | None:
    """Return the directory that holds the assets, if there is one."""

    candidates: list[Path] = []
    if is_frozen():
        # ``--include-data-dir=assets=assets`` lands next to the executable.
        candidates.append(Path(sys.executable).resolve().parent / ASSETS_DIRECTORY_NAME)
    # Source checkout: this file lives in ``ui/``, so the root is one level up.
    candidates.append(Path(__file__).resolve().parent.parent / ASSETS_DIRECTORY_NAME)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def icon_file_name(platform_name: str | None = None) -> str:
    """Return the icon file that fits the given platform."""

    name = platform.system() if platform_name is None else platform_name
    return _PLATFORM_ICON_FILES.get(name, DEFAULT_ICON_FILE)


def icon_path(platform_name: str | None = None) -> Path | None:
    """Return the icon file to use, or ``None`` when there is none."""

    directory = assets_directory()
    if directory is None:
        return None

    path = directory / icon_file_name(platform_name)
    if path.is_file():
        return path
    # Every platform can load a PNG, so it is a safe fallback.
    fallback = directory / DEFAULT_ICON_FILE
    return fallback if fallback.is_file() else None


def application_icon(platform_name: str | None = None) -> Any:
    """Return a ``QIcon`` for the window, or ``None`` when there is no artwork."""

    from PySide6.QtGui import QIcon

    path = icon_path(platform_name)
    if path is None:
        LOGGER.debug("No application icon was found")
        return None

    icon = QIcon(str(path))
    if icon.isNull():
        LOGGER.warning("The application icon could not be loaded: %s", path.name)
        return None
    return icon
