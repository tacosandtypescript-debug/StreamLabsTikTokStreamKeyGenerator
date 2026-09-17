"""Emoji the system cannot draw are removed, not shown as empty boxes."""

from __future__ import annotations

import pytest

from ui import text as text_tools


@pytest.fixture
def no_emoji_font(monkeypatch):
    """Pretend this machine has no font able to draw an emoji."""

    monkeypatch.setattr(text_tools, "emoji_font_name", lambda: "")
    return monkeypatch


@pytest.fixture
def with_emoji_font(monkeypatch):
    monkeypatch.setattr(text_tools, "emoji_font_name", lambda: "Segoe UI Emoji")
    return monkeypatch


def test_a_system_with_an_emoji_font_keeps_them(with_emoji_font):
    assert text_tools.emoji_is_available() is True
    assert text_tools.strip_unsupported_emoji("🔥 Creador") == "🔥 Creador"


def test_a_system_without_an_emoji_font_has_them_removed(no_emoji_font):
    assert text_tools.emoji_is_available() is False
    assert text_tools.strip_unsupported_emoji("🔥Creador de Fortnite MX 🔥") == (
        "Creador de Fortnite MX"
    )


def test_a_full_biography_stays_readable(no_emoji_font):
    bio = "🔥Creador de Fortnite MX 🔥 🔥Noticias/Actualizaciones🔥 ✉ khetzalgg@gmail.com"

    cleaned = text_tools.strip_unsupported_emoji(bio)

    assert "🔥" not in cleaned
    assert "✉" not in cleaned
    assert "Creador de Fortnite MX" in cleaned
    assert "Noticias/Actualizaciones" in cleaned
    assert "khetzalgg@gmail.com" in cleaned
    assert "  " not in cleaned


def test_ordinary_symbols_are_never_touched(no_emoji_font):
    # Arrows, quotes and typographic punctuation are not emoji: removing them
    # would damage perfectly good text.
    original = "Usa «OBS» → Ajustes; precio 10 € · 50 % — listo"

    assert text_tools.strip_unsupported_emoji(original) == original


def test_a_stripped_emoji_does_not_leave_a_space_before_punctuation(no_emoji_font):
    assert text_tools.strip_unsupported_emoji("hola 🔥. adiós") == "hola. adiós"


def test_empty_text_is_left_alone(no_emoji_font):
    assert text_tools.strip_unsupported_emoji("") == ""


def test_the_fallback_goes_after_the_desktop_choice(qapp, with_emoji_font):
    original = qapp.font()
    try:
        assert text_tools.install_emoji_fallback(qapp) is True
        families = qapp.font().families()
        assert families[-1] == "Segoe UI Emoji"
        assert families[0] == (original.families() or [original.family()])[0]
    finally:
        qapp.setFont(original)


def test_the_fallback_is_not_installed_twice(qapp, with_emoji_font):
    original = qapp.font()
    try:
        assert text_tools.install_emoji_fallback(qapp) is True
        assert text_tools.install_emoji_fallback(qapp) is False
    finally:
        qapp.setFont(original)


def test_without_an_emoji_font_there_is_nothing_to_install(qapp, no_emoji_font):
    original = qapp.font()
    try:
        assert text_tools.install_emoji_fallback(qapp) is False
        assert qapp.font().families() == original.families()
    finally:
        qapp.setFont(original)


def test_the_question_can_always_be_asked():
    # Unpatched, on whatever machine runs the suite: an answer must come back.
    assert isinstance(text_tools.emoji_font_name(), str)
    assert text_tools.emoji_font_name() in ("", *text_tools.EMOJI_FAMILIES)
