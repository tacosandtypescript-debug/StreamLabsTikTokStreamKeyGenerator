"""Remembering the window size and position between runs.

The logic that decides whether a saved geometry is still usable is kept free of
Qt so it can be tested directly: monitors get unplugged, and a window restored
onto a screen that no longer exists cannot be reached by the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

MINIMUM_WIDTH = 800
MINIMUM_HEIGHT = 600
# Anything below this is not a real geometry, just whatever Qt had before the
# window was ever shown.
MINIMUM_SAVED_SIZE = 200

ScreenRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class WindowGeometry:
    """A size, an optional position and whether the window was maximized."""

    width: int
    height: int
    x: int | None = None
    y: int | None = None
    maximized: bool = False


def _overlaps_any_screen(
    width: int,
    height: int,
    x: int,
    y: int,
    screens: Sequence[ScreenRect],
) -> bool:
    """Return whether a window at that position would be visible somewhere."""

    for left, top, screen_width, screen_height in screens:
        horizontally = x < left + screen_width and x + width > left
        vertically = y < top + screen_height and y + height > top
        if horizontally and vertically:
            return True
    return False


def sanitized_position(
    width: int,
    height: int,
    x: int | None,
    y: int | None,
    screens: Sequence[ScreenRect] = (),
) -> tuple[int, int] | None:
    """Return a usable ``(x, y)``, or ``None`` when the window should be centred.

    Used for a resizable window and for a fixed-size one, where only the position
    can be restored.
    """

    if x is None or y is None:
        return None
    if width <= 0 or height <= 0:
        return None
    if screens and not _overlaps_any_screen(width, height, int(x), int(y), screens):
        return None
    return int(x), int(y)


def sanitized_geometry(
    width: int | None,
    height: int | None,
    x: int | None,
    y: int | None,
    screens: Sequence[ScreenRect] = (),
    maximized: bool = False,
) -> WindowGeometry | None:
    """Return a usable geometry, or ``None`` when nothing sensible was saved.

    The size is raised to the minimum the window accepts, and a position that no
    longer lands on any screen is dropped so Qt can centre the window instead.
    """

    if not width or not height:
        return None
    if width < MINIMUM_SAVED_SIZE or height < MINIMUM_SAVED_SIZE:
        return None

    width = max(int(width), MINIMUM_WIDTH)
    height = max(int(height), MINIMUM_HEIGHT)

    position = sanitized_position(width, height, x, y, screens)
    if position is None:
        return WindowGeometry(width, height, maximized=maximized)
    return WindowGeometry(width, height, position[0], position[1], maximized)


def available_screens() -> list[ScreenRect]:
    """Return every screen's usable area as ``(left, top, width, height)``."""

    from PySide6.QtGui import QGuiApplication

    screens: list[ScreenRect] = []
    for screen in QGuiApplication.screens():
        area = screen.availableGeometry()
        screens.append((area.x(), area.y(), area.width(), area.height()))
    return screens


def restore_geometry(window: Any, geometry: WindowGeometry, *, size: bool = True) -> None:
    """Apply ``geometry`` to ``window``.

    ``size=False`` restores only the position, which is what a fixed-size window
    needs: its size comes from its content, not from what was saved.
    """

    if size:
        window.resize(geometry.width, geometry.height)
    if geometry.x is not None and geometry.y is not None:
        window.move(geometry.x, geometry.y)
    if size and geometry.maximized:
        from PySide6.QtCore import Qt

        window.setWindowState(window.windowState() | Qt.WindowState.WindowMaximized)


def capture_geometry(window: Any) -> WindowGeometry:
    """Return the geometry worth remembering.

    When the window is maximized the *normal* rectangle is stored, so that
    un-maximizing after a restart gives back the size the user had chosen.
    """

    maximized = bool(window.isMaximized())
    rect = window.normalGeometry() if maximized else window.geometry()
    if rect.width() < MINIMUM_SAVED_SIZE or rect.height() < MINIMUM_SAVED_SIZE:
        rect = window.geometry()
    return WindowGeometry(rect.width(), rect.height(), rect.x(), rect.y(), maximized)
