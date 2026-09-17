"""A very small translation layer.

Every user-facing message of the application is written in Spanish, which is also
the source language, so :func:`tr` returns its argument untouched until a catalog
is registered for the active language. Adding a language therefore means adding a
catalog and, at most, wrapping the remaining literals: a string that was not
translated still shows the Spanish text instead of an empty label or a key.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping

LOGGER = logging.getLogger(__name__)

SOURCE_LANGUAGE = "es"
LANGUAGE_ENV_VAR = "STREAMLABS_KEYGEN_LANG"

_catalogs: dict[str, dict[str, str]] = {}
_language = SOURCE_LANGUAGE


def _normalize(language: str | None) -> str:
    """Reduce a language tag such as ``pt_BR`` to a bare, lower-case code."""

    if not language:
        return ""
    return language.strip().lower().replace("_", "-").split("-", 1)[0]


def available_languages() -> tuple[str, ...]:
    """Return the source language plus every language that has a catalog."""

    return (SOURCE_LANGUAGE, *sorted(_catalogs))


def register_catalog(language: str, catalog: Mapping[str, str]) -> None:
    """Register the translations of one language.

    The mapping is copied, so a caller mutating its own dictionary afterwards
    cannot change what is displayed.
    """

    code = _normalize(language)
    if not code:
        raise ValueError("El idioma no puede estar vacío.")
    if code == SOURCE_LANGUAGE:
        raise ValueError("El idioma de origen no necesita catálogo.")
    _catalogs[code] = dict(catalog)
    LOGGER.debug("Registered %s translations for %r", len(catalog), code)


def set_language(language: str | None = None) -> str:
    """Select the active language and return its code.

    ``None`` reads the ``STREAMLABS_KEYGEN_LANG`` environment variable. An
    unknown or unavailable language falls back to the source language instead of
    failing, so a bad value can never leave the interface unreadable.
    """

    global _language

    requested = language if language is not None else os.environ.get(LANGUAGE_ENV_VAR)
    code = _normalize(requested)
    if not code or code == SOURCE_LANGUAGE:
        _language = SOURCE_LANGUAGE
        return _language
    if code not in _catalogs:
        LOGGER.warning("No catalog for %r; using %s", requested, SOURCE_LANGUAGE)
        _language = SOURCE_LANGUAGE
        return _language
    _language = code
    return _language


def current_language() -> str:
    """Return the code of the active language."""

    return _language


def tr(text: str) -> str:
    """Return ``text`` translated into the active language."""

    if _language == SOURCE_LANGUAGE:
        return text
    return _catalogs.get(_language, {}).get(text, text)
