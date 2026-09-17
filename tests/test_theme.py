"""Theme selection and the shortcut table."""

from __future__ import annotations

from PySide6.QtGui import QPalette

from ui import theme
from ui.shortcuts import SHORTCUTS


def test_an_explicit_choice_always_wins():
    assert theme.resolve_theme("dark", False) == "dark"
    assert theme.resolve_theme("light", True) == "light"
    assert theme.resolve_theme("DARK", False) == "dark"
    assert theme.resolve_theme(" dark ", None) == "dark"


def test_without_a_choice_the_desktop_decides():
    assert theme.resolve_theme(None, True) == "dark"
    assert theme.resolve_theme(None, False) == "light"


def test_an_unknown_or_missing_answer_follows_the_desktop():
    assert theme.resolve_theme("neon", True) == "dark"
    assert theme.resolve_theme("", None) == "light"
    assert theme.resolve_theme(None, None) == "light"


def test_applying_dark_sets_a_genuinely_dark_palette(qapp):
    original_style = qapp.style().objectName()
    original_palette = qapp.palette()
    try:
        applied = theme.apply_theme(qapp, "dark")
        palette = qapp.palette()
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)

        assert applied == "dark"
        assert window.lightness() < 80
        assert palette.color(QPalette.ColorRole.Base).lightness() < 80
        assert text.lightness() > 150
    finally:
        qapp.setStyle(original_style)
        qapp.setPalette(original_palette)


def test_applying_light_leaves_the_palette_alone(qapp):
    before = qapp.palette().color(QPalette.ColorRole.Window)

    applied = theme.apply_theme(qapp, "light")

    assert applied == "light"
    assert qapp.palette().color(QPalette.ColorRole.Window) == before


def test_the_environment_variable_is_the_default_request(monkeypatch, qapp):
    original_palette = qapp.palette()
    monkeypatch.setenv(theme.THEME_ENV_VAR, "dark")
    try:
        assert theme.apply_theme(qapp) == "dark"
    finally:
        qapp.setPalette(original_palette)


def test_every_shortcut_has_a_unique_sequence_and_a_target():
    sequences = [sequence for sequence, _ in SHORTCUTS]
    targets = [target for _, target in SHORTCUTS]
    prefixes = ("start_", "end_", "show_", "export_", "open_")

    assert len(set(sequences)) == len(sequences)
    assert len(set(targets)) == len(targets)
    assert all(target.startswith(prefixes) for target in targets)
