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


def test_the_windows_setting_means_dark_when_it_is_zero():
    assert theme._dark_from_apps_theme(0) is True
    assert theme._dark_from_apps_theme(1) is False


def test_anything_that_is_not_zero_or_one_is_not_an_answer():
    assert theme._dark_from_apps_theme("0") is None
    assert theme._dark_from_apps_theme(None) is None
    assert theme._dark_from_apps_theme(True) is None
    # Windows only writes 0 or 1; any other number is read as "not dark", which is
    # the safe direction: a light interface is always usable.
    assert theme._dark_from_apps_theme(2) is False


def test_qt_is_asked_first(monkeypatch):
    consulted = []
    monkeypatch.setattr(theme, "_qt_color_scheme_is_dark", lambda: False)
    monkeypatch.setattr(
        theme,
        "_windows_prefers_dark",
        lambda: consulted.append(True) or True,
    )

    assert theme.system_prefers_dark() is False
    assert consulted == []


def test_the_windows_setting_is_used_when_qt_does_not_know(monkeypatch):
    monkeypatch.setattr(theme, "_qt_color_scheme_is_dark", lambda: None)
    monkeypatch.setattr(theme, "_windows_prefers_dark", lambda: True)

    assert theme.system_prefers_dark() is True


def test_without_any_answer_the_desktop_is_simply_unknown(monkeypatch):
    monkeypatch.setattr(theme, "_qt_color_scheme_is_dark", lambda: None)
    monkeypatch.setattr(theme, "_windows_prefers_dark", lambda: None)

    assert theme.system_prefers_dark() is None


def test_the_registry_answer_can_always_be_asked_for():
    # On Windows it answers; on the other systems it says it does not know.
    assert theme._windows_prefers_dark() in (True, False, None)


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
