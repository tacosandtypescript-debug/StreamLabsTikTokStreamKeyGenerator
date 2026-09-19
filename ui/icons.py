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
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

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


def play_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn triangle, for the button that prepares the stream."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    triangle = QPainterPath()
    triangle.moveTo(4.5 * unit, 2.5 * unit)
    triangle.lineTo(13 * unit, 8 * unit)
    triangle.lineTo(4.5 * unit, 13.5 * unit)
    triangle.closeSubpath()
    painter.setBrush(QColor(color))
    painter.drawPath(triangle)
    painter.end()
    return QIcon(pixmap)


def stop_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn square, for the button that finishes the stream."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(3.5 * unit, 3.5 * unit, 9 * unit, 9 * unit), unit, unit)
    painter.end()
    return QIcon(pixmap)


def save_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn floppy disk, for the button that saves the settings."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    # The body, with the corner cut off the way the real icon has it.
    body = QPainterPath()
    body.moveTo(2 * unit, 2 * unit)
    body.lineTo(11.5 * unit, 2 * unit)
    body.lineTo(14 * unit, 4.5 * unit)
    body.lineTo(14 * unit, 14 * unit)
    body.lineTo(2 * unit, 14 * unit)
    body.closeSubpath()
    painter.drawPath(body)
    # The label at the bottom and the shutter at the top.
    painter.drawRect(QRectF(5 * unit, 9.5 * unit, 6 * unit, 4.5 * unit))
    painter.drawRect(QRectF(5.5 * unit, 2 * unit, 5 * unit, 3.5 * unit))
    painter.end()
    return QIcon(pixmap)


def refresh_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn circular arrow, for the button that reloads the account."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    # Three quarters of a circle, so the gap is where the arrowhead goes.
    painter.drawArc(QRectF(3 * unit, 3 * unit, 10 * unit, 10 * unit), 60 * 16, 280 * 16)
    head = QPainterPath()
    head.moveTo(13.0 * unit, 4.6 * unit)
    head.lineTo(9.2 * unit, 5.4 * unit)
    head.lineTo(11.9 * unit, 8.0 * unit)
    head.closeSubpath()
    painter.setBrush(QColor(color))
    painter.drawPath(head)
    painter.end()
    return QIcon(pixmap)


def user_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn head and shoulders, for the account button."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawEllipse(QRectF(5.5 * unit, 2 * unit, 5 * unit, 5 * unit))
    # An open arc, so it reads as a pair of shoulders rather than a closed blob.
    painter.drawArc(QRectF(2.5 * unit, 9 * unit, 11 * unit, 10 * unit), 0, 180 * 16)
    painter.end()
    return QIcon(pixmap)


def key_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn key, for the token screen and the stream key field."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawEllipse(QRectF(1.5 * unit, 5.5 * unit, 6 * unit, 6 * unit))
    painter.drawLine(QPointF(7 * unit, 7 * unit), QPointF(14.5 * unit, 7 * unit))
    painter.drawLine(QPointF(11.5 * unit, 7 * unit), QPointF(11.5 * unit, 10 * unit))
    painter.drawLine(QPointF(14 * unit, 7 * unit), QPointF(14 * unit, 9.5 * unit))
    painter.end()
    return QIcon(pixmap)


def link_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return two drawn chain links, for the server URL field."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    painter.drawRoundedRect(
        QRectF(1.0 * unit, 5.5 * unit, 9 * unit, 5 * unit), 2.5 * unit, 2.5 * unit
    )
    painter.drawRoundedRect(
        QRectF(6.0 * unit, 5.5 * unit, 9 * unit, 5 * unit), 2.5 * unit, 2.5 * unit
    )
    painter.drawLine(QPointF(6.6 * unit, 8 * unit), QPointF(9.4 * unit, 8 * unit))
    painter.end()
    return QIcon(pixmap)


def shield_icon(size: int = 16, color: str = "#000000") -> QIcon:
    """Return a drawn shield, for the permission the account needs."""

    pixmap = _blank_pixmap(size)
    painter = _start_painting(pixmap, color, size)
    unit = size / 16.0
    shield = QPainterPath()
    shield.moveTo(8 * unit, 1.8 * unit)
    shield.lineTo(13.5 * unit, 4 * unit)
    shield.lineTo(13.5 * unit, 8.5 * unit)
    shield.cubicTo(
        13.5 * unit, 11.5 * unit, 11 * unit, 13.3 * unit, 8 * unit, 14.4 * unit
    )
    shield.cubicTo(
        5 * unit, 13.3 * unit, 2.5 * unit, 11.5 * unit, 2.5 * unit, 8.5 * unit
    )
    shield.lineTo(2.5 * unit, 4 * unit)
    shield.closeSubpath()
    painter.drawPath(shield)
    painter.end()
    return QIcon(pixmap)
