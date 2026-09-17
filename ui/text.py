"""Text the system can actually draw.

Two problems look identical on screen and have nothing to do with each other:

* the bytes were decoded wrongly, which turns "🔥" into "ðŸ”¥" — that is a bug in
  the code and is checked elsewhere;
* the text is perfect but **no installed font has the character**, so Qt draws an
  empty box.

This module deals with the second one. Emoji arrive inside the profile biography,
which belongs to TikTok and not to us, so they cannot be dropped from the source:
the decision has to be made when drawing, based on the fonts this machine has.
"""

from __future__ import annotations

import logging
import platform
import re
from functools import lru_cache
from typing import Any

LOGGER = logging.getLogger(__name__)

# Emoji fonts, in the order they are worth trying. Unavailable names are simply
# ignored by Qt, so the whole list can be handed over on every platform.
EMOJI_FAMILIES: tuple[str, ...] = (
    "Segoe UI Emoji",
    "Segoe UI Symbol",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Noto Emoji",
    "Symbola",
)
EMOJI_PROBE = "🔥"

# Emoji blocks. Deliberately narrow: arrows (2190-21FF) and typographic
# punctuation are ordinary characters and stripping them would damage the text.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f000-\U0001faff"  # pictographs, faces, objects, flags
    "\U00002600-\U000027bf"  # miscellaneous symbols and dingbats
    "\U00002b00-\U00002bff"  # additional symbols and arrows
    "\U0000fe0f"  # variation selector, which only decorates an emoji
    "]+"
)


def _font_database() -> Any:
    from PySide6.QtGui import QFontDatabase

    return QFontDatabase


@lru_cache(maxsize=1)
def emoji_font_name() -> str:
    """Return an installed emoji font, or an empty string when there is none."""

    try:
        database = _font_database()
        families = set(database.families())
    except Exception:  # pragma: no cover - no Qt, or no font database
        return ""
    for name in EMOJI_FAMILIES:
        if name in families:
            return name
    return ""


def emoji_is_available() -> bool:
    """Return whether this machine can draw emoji at all."""

    return bool(emoji_font_name())


def strip_unsupported_emoji(text: str) -> str:
    """Remove emoji when no font can draw them, and leave the text alone otherwise.

    A box in the middle of a biography looks like a broken application; the same
    sentence without the emoji reads perfectly.
    """

    if not text or emoji_is_available():
        return text
    cleaned = _EMOJI_PATTERN.sub(" ", text)
    # Collapse the gaps the removal leaves behind, without touching the rest.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    if cleaned != text:
        LOGGER.debug("Emoji removed: no installed font can draw them")
    return cleaned


def install_emoji_fallback(app: Any) -> bool:
    """Add the emoji fonts to the application font's fallback list.

    Qt usually falls back on its own, but not always, and never when the widget
    carries its own font. The desktop's own choice stays first, so nothing about
    the interface changes except that emoji can now be drawn.
    """

    name = emoji_font_name()
    if not name:
        LOGGER.debug("No emoji font on this system (%s)", platform.system())
        return False

    font = app.font()
    families = list(font.families()) or ([font.family()] if font.family() else [])
    if name in families:
        return False
    font.setFamilies([*families, name])
    app.setFont(font)
    LOGGER.debug("Emoji fallback added to the application font: %s", name)
    return True
