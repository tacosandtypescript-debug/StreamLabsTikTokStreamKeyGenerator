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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

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

    path = icon_path(platform_name)
    if path is None:
        LOGGER.debug("No application icon was found")
        return None

    icon = QIcon(str(path))
    if icon.isNull():
        LOGGER.warning("The application icon could not be loaded: %s", path.name)
        return None
    return icon


def _blank_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _start_painting(pixmap: QPixmap, color: str, size: int) -> QPainter:
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(size / 11.0, 1.2))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return painter


def copy_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn "copy" icon.

    Drawn instead of typed on purpose: an emoji or a symbol glyph depends on the
    fonts the platform happens to have installed, and shows up as an empty box
    when they are missing, which is exactly what the previous buttons did.
    """

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawRoundedRect(
        QRectF(1.5 * unit, 1.5 * unit, 8.5 * unit, 8.5 * unit), 2 * unit, 2 * unit
    )
    painter.drawRoundedRect(
        QRectF(6 * unit, 6 * unit, 8.5 * unit, 8.5 * unit), 2 * unit, 2 * unit
    )
    painter.end()
    return QIcon(pixmap)


def eye_icon(size: int = 16, color: str = "#000000", *, open_eye: bool = True) -> QIcon:
    """Return a drawn "show/hide" icon."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawEllipse(QRectF(1.5 * unit, 4.0 * unit, 13 * unit, 8 * unit))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(6.4 * unit, 6.4 * unit, 3.2 * unit, 3.2 * unit))
    if not open_eye:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(2.5 * unit, 13 * unit), QPointF(13.5 * unit, 3 * unit))
    painter.end()
    return QIcon(pixmap)


def check_icon(size: int = 16, color: str = "#12854a") -> QIcon:
    """Return a drawn tick, used to confirm a copy without a dialog."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(3 * unit, 8.5 * unit),
                QPointF(6.5 * unit, 12 * unit),
                QPointF(13 * unit, 4.5 * unit),
            ]
        )
    )
    painter.end()
    return QIcon(pixmap)
