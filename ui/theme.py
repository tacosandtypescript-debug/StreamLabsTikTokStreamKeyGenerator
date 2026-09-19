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

# The network's own colours, by name, so the table below says what it is doing.
TIKTOK_CYAN = "#25f4ee"
TIKTOK_ROSE = "#fe2c55"
TIKTOK_BLACK = "#010101"
TIKTOK_WHITE = "#ffffff"

_TOKENS: dict[str, dict[str, str]] = {
    LIGHT: {
        "bg": "#f1f1f2",
        "card": "#ffffff",
        "border": "#e3e3e5",
        "divider": "#e8e8ea",
        "text": "#161823",
        "muted": "#6b6b76",
        "disabled": "#a6a6b0",
        "field": "#f8f8f9",
        "fieldBorder": "#d4d4d9",
        # The signature cyan cannot carry white text and looks washed out with
        # dark text on a white page, so it fills the button (with the black the
        # network also labels it with) while a readable teal draws links, focus
        # rings and selection.
        "primary": TIKTOK_CYAN,
        "primaryHover": "#0fd9d2",
        "primaryText": TIKTOK_BLACK,
        "link": "#0f8b8d",
        "linkHover": "#0b6e70",
        # The other signature colour, kept for the one action that throws work
        # away: ending the stream.
        "danger": TIKTOK_ROSE,
        "dangerHover": "#e61f47",
        "dangerText": TIKTOK_WHITE,
        "neutral": "#8a8a95",
        "ok": "#12854a",
        "warn": "#b06a00",
        "error": "#e0245e",
        # A prepared stream is an active state, not a problem, so it stays green
        # while red is kept for errors — a brighter green than "ok", because a
        # running session should read as more alive than a passed check.
        "live": "#00b85c",
    },
    DARK: {
        # The network's near-black. The cards are a hair lighter than the page and
        # carry only a whisper of a border: on black, an outlined box reads as a
        # form to fill in, while a barely-raised panel reads as a section — which is
        # what the profile does, and what these are.
        "bg": TIKTOK_BLACK,
        "card": "#0f0f0f",
        "border": "#222222",
        "divider": "#262626",
        "text": "#f1f1f2",
        "muted": "#9a9aa5",
        "disabled": "#6b6b76",
        # Fields sit a step further up again, because a field that cannot be seen
        # cannot be found: here the edge is what says "type here".
        "field": "#171717",
        "fieldBorder": "#333333",
        "primary": TIKTOK_CYAN,
        "primaryHover": "#5ff8f2",
        "primaryText": TIKTOK_BLACK,
        "link": TIKTOK_CYAN,
        "linkHover": "#5ff8f2",
        "danger": TIKTOK_ROSE,
        "dangerHover": "#ff4d6d",
        "dangerText": TIKTOK_WHITE,
        "neutral": "#8a8a95",
        "ok": "#25d366",
        "warn": "#ffc93c",
        "error": "#ff5c7a",
        "live": "#00f2a0",
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

    /* In the dark theme the cards have no fill of their own: the profile is drawn
       edge to edge on black, and the surface comes from the fields and the
       hairline dividers instead of from a stack of outlined boxes. */
    QFrame#card, QFrame#banner {{
        background: {t["card"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}
    QFrame#banner {{ border-left: 4px solid {t["neutral"]}; }}
    QFrame#banner[state="ok"] {{ border-left-color: {t["ok"]}; }}
    QFrame#banner[state="warn"] {{ border-left-color: {t["warn"]}; }}
    QFrame#banner[state="error"] {{ border-left-color: {t["error"]}; }}
    QFrame#banner[state="live"] {{ border-left-color: {t["live"]}; }}

    QLabel#bannerTitle {{ font-size: 15px; font-weight: 600; }}
    /* The profile header, at the size the network sets its own name: the handle is
       the identity, so it is the largest thing on the page. */
    QLabel#profileName {{ font-size: 22px; font-weight: 700; }}
    QLabel#profileStats {{ color: {t["muted"]}; }}
    QLabel#bannerDetail, QLabel#muted, QLabel#cardSummary {{ color: {t["muted"]}; }}
    /* The card heading is a line of small text with a hairline under it, so a card
       is read as a titled section instead of as a box that happens to have a word
       at the top. */
    QLabel#cardTitle {{
        color: {t["muted"]};
        font-weight: 700;
        font-size: 12px;
        padding-bottom: 4px;
        border-bottom: 1px solid {t["divider"]};
    }}
    QLabel#fieldLabel {{ color: {t["muted"]}; }}

    /* The three numbers under the name: a large figure with a small caption under
       it, which is how the profile itself counts followers, likes and videos. */
    QLabel#statValue {{ font-size: 17px; font-weight: 700; }}
    QLabel#statLabel {{ color: {t["muted"]}; font-size: 12px; }}
    QFrame#statDivider {{ background: {t["divider"]}; border: none; }}

    /* The summary strip: small capitals above the value, separated by hairlines
       instead of being boxed, so it reads as one row and not three cards. */
    QFrame#summaryStrip {{
        background: {t["card"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}
    QFrame#summaryDivider {{ background: {t["border"]}; border: none; }}
    QLabel#summaryKey {{
        color: {t["muted"]};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#summaryValue {{ font-size: 14px; font-weight: 600; }}
    QLabel#summaryValue[state="ok"] {{ color: {t["ok"]}; }}
    QLabel#summaryValue[state="warn"] {{ color: {t["warn"]}; }}
    QLabel#summaryValue[state="error"] {{ color: {t["error"]}; }}
    QLabel#summaryValue[state="live"] {{ color: {t["live"]}; }}

    QLabel#badge {{ color: {t["muted"]}; font-weight: 600; }}
    QLabel#badge[state="ok"] {{ color: {t["ok"]}; }}
    QLabel#badge[state="warn"] {{ color: {t["warn"]}; }}
    QLabel#badge[state="error"] {{ color: {t["error"]}; }}

    QLineEdit {{
        background: {t["field"]};
        border: 1px solid {t["fieldBorder"]};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {t["link"]};
        selection-color: {t["primaryText"]};
    }}
    QLineEdit:hover {{ border-color: {t["muted"]}; }}
    /* The focus ring keeps the border the same width as the resting state, so the
       field does not jump a pixel every time the caret enters it. It is told apart
       by colour and by a brighter fill instead. */
    QLineEdit:focus {{
        border: 1px solid {t["link"]};
        background: {t["card"]};
    }}
    QLineEdit[readOnly="true"] {{ background: {t["card"]}; }}
    QLineEdit[readOnly="true"]:hover {{ border-color: {t["fieldBorder"]}; }}
    QLineEdit:disabled {{ color: {t["disabled"]}; background: {t["bg"]}; }}

    QPushButton {{
        background: {t["card"]};
        border: 1px solid {t["fieldBorder"]};
        border-radius: 8px;
        padding: 8px 15px;
        font-weight: 500;
    }}
    QPushButton:hover {{ border-color: {t["link"]}; color: {t["link"]}; }}
    QPushButton:pressed {{ background: {t["bg"]}; }}
    QPushButton:disabled {{ color: {t["disabled"]}; border-color: {t["border"]}; }}

    QPushButton#primary {{
        background: {t["primary"]};
        border: 1px solid {t["primary"]};
        color: {t["primaryText"]};
        font-weight: 700;
        padding: 10px 24px;
    }}
    QPushButton#primary:hover {{
        background: {t["primaryHover"]};
        border-color: {t["primaryHover"]};
        color: {t["primaryText"]};
    }}
    QPushButton#primary:pressed {{ background: {t["primary"]}; }}
    QPushButton#primary:disabled {{
        background: {t["bg"]};
        border-color: {t["border"]};
        color: {t["disabled"]};
    }}

    /* Ending a stream throws work away, so it carries the other signature
       colour instead of looking like every other button. */
    QPushButton#danger {{
        background: {t["card"]};
        border: 1px solid {t["danger"]};
        color: {t["danger"]};
        font-weight: 600;
    }}
    QPushButton#danger:hover {{
        background: {t["danger"]};
        border-color: {t["danger"]};
        color: {t["dangerText"]};
    }}
    QPushButton#danger:disabled {{
        background: {t["bg"]};
        border-color: {t["border"]};
        color: {t["disabled"]};
    }}

    QPushButton#link {{
        background: transparent;
        border: none;
        color: {t["link"]};
        text-align: left;
        padding: 6px 2px;
        font-weight: 600;
    }}
    QPushButton#link:hover {{ color: {t["linkHover"]}; }}
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
    QMenu::item:selected {{ background: {t["link"]}; color: {t["primaryText"]}; }}
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
    QCheckBox::indicator:hover {{ border-color: {t["link"]}; }}
    QCheckBox::indicator:checked {{
        background: {t["primary"]};
        border-color: {t["link"]};
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
