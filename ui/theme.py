"""Dark-mode support.

Qt 6.5 and newer already report the desktop colour scheme, so the application
only has to react to it. Setting an explicit palette is what actually makes the
widgets dark: the default style on Windows follows the system theme, but a
palette is the portable way to get the same result on every platform.
"""

from __future__ import annotations

import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)

THEME_ENV_VAR = "STREAMLABS_KEYGEN_THEME"
LIGHT = "light"
DARK = "dark"

_DARK_WINDOW = "#1b2430"
_DARK_BASE = "#141b24"
_DARK_TEXT = "#e8eef5"
_DARK_DISABLED = "#6b7a8c"
_DARK_HIGHLIGHT = "#2563eb"


def resolve_theme(requested: str | None, system_is_dark: bool | None) -> str:
    """Decide the theme to use.

    An explicit choice always wins; otherwise the desktop decides, and an
    unknown answer from the platform falls back to the light theme.
    """

    normalized = (requested or "").strip().lower()
    if normalized in {LIGHT, DARK}:
        return normalized
    return DARK if system_is_dark else LIGHT


def system_prefers_dark() -> bool | None:
    """Return the desktop colour scheme, or ``None`` when it cannot be read."""

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
    except Exception:  # pragma: no cover - needs an app, old Qt, or odd theme
        LOGGER.debug("The system colour scheme could not be read", exc_info=True)
        return None

    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    # Qt.ColorScheme.Unknown: the platform has no opinion.
    return None


def dark_palette() -> Any:
    """Build the dark palette used by the application."""

    from PySide6.QtGui import QColor, QPalette

    window = QColor(_DARK_WINDOW)
    base = QColor(_DARK_BASE)
    text = QColor(_DARK_TEXT)
    disabled = QColor(_DARK_DISABLED)

    palette = QPalette()
    roles = (
        (QPalette.ColorRole.Window, window),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Base, base),
        (QPalette.ColorRole.AlternateBase, window),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.Button, window),
        (QPalette.ColorRole.ButtonText, text),
        (QPalette.ColorRole.ToolTipBase, base),
        (QPalette.ColorRole.ToolTipText, text),
        (QPalette.ColorRole.PlaceholderText, disabled),
        (QPalette.ColorRole.Highlight, QColor(_DARK_HIGHLIGHT)),
        (QPalette.ColorRole.HighlightedText, QColor("#ffffff")),
    )
    for role, color in roles:
        palette.setColor(role, color)

    # Disabled widgets need their own colour: the default one is nearly black
    # and becomes unreadable on a dark background.
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return palette


def apply_theme(app: Any, requested: str | None = None) -> str:
    """Apply the resolved theme and return its name.

    ``requested`` defaults to the ``STREAMLABS_KEYGEN_THEME`` environment
    variable, which accepts ``dark``, ``light`` or anything else for "follow the
    desktop".
    """

    if requested is None:
        requested = os.environ.get(THEME_ENV_VAR)
    theme = resolve_theme(requested, system_prefers_dark())
    if theme == DARK:
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
    return theme
