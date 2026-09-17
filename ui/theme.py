"""Theme: the palette, the colour tokens and the stylesheet.

Colours live in one table so that every widget asks for a token instead of
hard-coding a value, which is what keeps the dark theme consistent. The
stylesheet is generated from that table, so adding a state means adding a row.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

LOGGER = logging.getLogger(__name__)

THEME_ENV_VAR = "STREAMLABS_KEYGEN_THEME"
LIGHT = "light"
DARK = "dark"

_TOKENS: dict[str, dict[str, str]] = {
    LIGHT: {
        "bg": "#f2f4f7",
        "card": "#ffffff",
        "border": "#dde3ea",
        "text": "#1b2430",
        "muted": "#63707f",
        "disabled": "#a9b3bf",
        "field": "#ffffff",
        "fieldBorder": "#c6d0da",
        "primary": "#2563eb",
        "primaryHover": "#1d4ed8",
        "primaryText": "#ffffff",
        "neutral": "#8794a3",
        "ok": "#12854a",
        "warn": "#a16207",
        "error": "#c0392b",
        # A prepared stream is an active state, not a problem: red stays for
        # errors only, which is why this one is the accent blue.
        "live": "#2563eb",
    },
    DARK: {
        "bg": "#141b24",
        "card": "#1b2430",
        "border": "#2b3746",
        "text": "#e8eef5",
        "muted": "#93a2b3",
        "disabled": "#6b7a8c",
        "field": "#111823",
        "fieldBorder": "#33415a",
        "primary": "#3b82f6",
        "primaryHover": "#2f74e0",
        "primaryText": "#ffffff",
        "neutral": "#7c8b9c",
        "ok": "#34d399",
        "warn": "#fbbf24",
        "error": "#f87171",
        "live": "#3b82f6",
    },
}

# The states a banner can be in; the accent of each one is a colour token.
BANNER_STATES = ("neutral", "ok", "warn", "error", "live")

_theme = LIGHT


def current_theme() -> str:
    """Return the theme that was applied last."""

    return _theme


def color_tokens(theme: str | None = None) -> dict[str, str]:
    """Return the colour table of ``theme`` (the active one by default)."""

    return _TOKENS.get(theme or _theme, _TOKENS[LIGHT])


def state_accent(theme: str, state: str) -> str:
    """Return the accent colour of a banner state."""

    tokens = color_tokens(theme)
    return tokens.get(state, tokens["neutral"])


def resolve_theme(requested: str | None, system_is_dark: bool | None) -> str:
    """Decide the theme to use.

    An explicit choice always wins; otherwise the desktop decides, and an unknown
    answer from the platform falls back to the light theme.
    """

    normalized = (requested or "").strip().lower()
    if normalized in {LIGHT, DARK}:
        return normalized
    return DARK if system_is_dark else LIGHT


def _qt_color_scheme_is_dark() -> bool | None:
    """Ask Qt, which knows on most desktops but answers ``Unknown`` on some."""

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


def _dark_from_apps_theme(value: Any) -> bool | None:
    """Turn Windows' ``AppsUseLightTheme`` into an answer: 0 is dark, 1 is light."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value == 0


def _windows_prefers_dark() -> bool | None:
    """Read the theme the user chose in Windows settings.

    Qt answers ``Unknown`` on a desktop that is clearly dark (it does on this
    machine), so the registry value the Settings app writes is consulted as well.
    """

    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - winreg exists only on Windows
        return None

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return None
    return _dark_from_apps_theme(value)


def system_prefers_dark() -> bool | None:
    """Return the desktop colour scheme, or ``None`` when it cannot be read."""

    answer = _qt_color_scheme_is_dark()
    if answer is not None:
        return answer
    return _windows_prefers_dark()


def dark_palette() -> Any:
    """Build the dark palette used by the application."""

    from PySide6.QtGui import QColor, QPalette

    tokens = color_tokens(DARK)
    window = QColor(tokens["card"])
    base = QColor(tokens["field"])
    text = QColor(tokens["text"])
    disabled = QColor(tokens["disabled"])

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
        (QPalette.ColorRole.Highlight, QColor(tokens["primary"])),
        (QPalette.ColorRole.HighlightedText, QColor(tokens["primaryText"])),
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


def stylesheet(theme: str) -> str:
    """Return the stylesheet of ``theme``, generated from its colour tokens."""

    t = color_tokens(theme)
    return f"""
    QWidget {{ color: {t["text"]}; }}
    QMainWindow, QWidget#central, QScrollArea, QWidget#scrollBody {{
        background: {t["bg"]};
    }}
    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{ background: {t["bg"]}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 5px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    QFrame#card, QFrame#banner {{
        background: {t["card"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
    }}
    QFrame#banner {{ border-left: 4px solid {t["neutral"]}; }}
    QFrame#banner[state="ok"] {{ border-left-color: {t["ok"]}; }}
    QFrame#banner[state="warn"] {{ border-left-color: {t["warn"]}; }}
    QFrame#banner[state="error"] {{ border-left-color: {t["error"]}; }}
    QFrame#banner[state="live"] {{ border-left-color: {t["live"]}; }}

    QLabel#bannerTitle {{ font-size: 15px; font-weight: 600; }}
    QLabel#profileName {{ font-size: 17px; font-weight: 600; }}
    QLabel#profileStats {{ color: {t["muted"]}; }}
    QLabel#bannerDetail, QLabel#muted, QLabel#cardSummary {{ color: {t["muted"]}; }}
    QLabel#cardTitle {{ color: {t["muted"]}; font-weight: 600; }}
    QLabel#fieldLabel {{ color: {t["muted"]}; }}

    QLabel#badge {{ color: {t["muted"]}; font-weight: 600; }}
    QLabel#badge[state="ok"] {{ color: {t["ok"]}; }}
    QLabel#badge[state="warn"] {{ color: {t["warn"]}; }}
    QLabel#badge[state="error"] {{ color: {t["error"]}; }}

    QLineEdit {{
        background: {t["field"]};
        border: 1px solid {t["fieldBorder"]};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {t["primary"]};
    }}
    QLineEdit:focus {{ border: 1px solid {t["primary"]}; }}
    QLineEdit[readOnly="true"] {{ background: {t["card"]}; }}
    QLineEdit:disabled {{ color: {t["disabled"]}; background: {t["bg"]}; }}

    QPushButton {{
        background: {t["card"]};
        border: 1px solid {t["fieldBorder"]};
        border-radius: 6px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ border-color: {t["primary"]}; }}
    QPushButton:pressed {{ background: {t["bg"]}; }}
    QPushButton:disabled {{ color: {t["disabled"]}; border-color: {t["border"]}; }}

    QPushButton#primary {{
        background: {t["primary"]};
        border: 1px solid {t["primary"]};
        color: {t["primaryText"]};
        font-weight: 600;
        padding: 9px 22px;
    }}
    QPushButton#primary:hover {{ background: {t["primaryHover"]}; }}
    QPushButton#primary:disabled {{
        background: {t["bg"]};
        border-color: {t["border"]};
        color: {t["disabled"]};
    }}

    QPushButton#link {{
        background: transparent;
        border: none;
        color: {t["primary"]};
        text-align: left;
        padding: 4px 2px;
    }}
    QPushButton#link:hover {{ color: {t["primaryHover"]}; }}
    QPushButton#link:disabled {{ color: {t["disabled"]}; }}

    QToolButton {{ border: none; background: transparent; padding: 4px; border-radius: 6px; }}
    QToolButton:hover {{ background: {t["bg"]}; }}
    QToolButton#sectionToggle {{ font-weight: 600; text-align: left; padding: 6px 4px; }}

    QListWidget {{
        background: {t["card"]};
        border: 1px solid {t["fieldBorder"]};
        border-radius: 6px;
    }}
    QStatusBar {{ background: {t["card"]}; border-top: 1px solid {t["border"]}; }}
    QStatusBar::item {{ border: none; }}
    QMenu {{ background: {t["card"]}; border: 1px solid {t["border"]}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t["primary"]}; color: {t["primaryText"]}; }}
    QProgressBar {{ background: {t["bg"]}; border: 1px solid {t["border"]}; border-radius: 4px; }}
    QProgressBar::chunk {{ background: {t["primary"]}; border-radius: 4px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {t["fieldBorder"]};
        border-radius: 4px;
        background: {t["field"]};
    }}
    QCheckBox::indicator:hover {{ border-color: {t["primary"]}; }}
    QCheckBox::indicator:checked {{
        background: {t["primary"]};
        border-color: {t["primary"]};
    }}
    QCheckBox::indicator:disabled {{ border-color: {t["border"]}; background: {t["bg"]}; }}
    QMessageBox {{ background: {t["card"]}; }}
    """


def apply_theme(app: Any, requested: str | None = None) -> str:
    """Apply the resolved theme and return its name.

    ``requested`` defaults to the ``STREAMLABS_KEYGEN_THEME`` environment
    variable, which accepts ``dark``, ``light`` or anything else for "follow the
    desktop".
    """

    global _theme

    if requested is None:
        requested = os.environ.get(THEME_ENV_VAR)
    theme = resolve_theme(requested, system_prefers_dark())

    if theme == DARK:
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
    app.setStyleSheet(stylesheet(theme))

    # Emoji end up on screen inside third-party text (the profile biography), and
    # not every Windows or Linux install can draw them out of the box.
    from ui.text import install_emoji_fallback

    install_emoji_fallback(app)

    _theme = theme
    return theme
