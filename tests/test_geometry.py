"""What the application remembers about the window, and what it throws away."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.geometry import (
    MINIMUM_HEIGHT,
    MINIMUM_WIDTH,
    WindowGeometry,
    capture_geometry,
    restore_geometry,
    sanitized_geometry,
    sanitized_position,
)

SCREENS = [(0, 0, 1920, 1080), (1920, 0, 1280, 1024)]


def test_nothing_saved_means_nothing_to_restore():
    assert sanitized_geometry(0, 0, None, None, SCREENS) is None
    assert sanitized_geometry(None, None, None, None, SCREENS) is None


def test_a_size_below_the_window_minimum_is_raised():
    geometry = sanitized_geometry(300, 200, None, None, SCREENS)

    assert geometry == WindowGeometry(MINIMUM_WIDTH, MINIMUM_HEIGHT)


def test_a_garbage_size_is_ignored():
    # Whatever Qt reports for a window that was never shown must not stick.
    assert sanitized_geometry(120, 90, 10, 10, SCREENS) is None
    assert sanitized_geometry(5000, 100, 10, 10, SCREENS) is None


def test_a_position_on_the_main_screen_is_kept():
    assert sanitized_geometry(1000, 700, 120, 80, SCREENS) == WindowGeometry(
        1000, 700, 120, 80
    )


def test_a_negative_position_on_a_screen_to_the_left_is_kept():
    screens = [(-1920, 0, 1920, 1080)] + SCREENS

    assert sanitized_geometry(1000, 700, -1500, 100, screens) == WindowGeometry(
        1000, 700, -1500, 100
    )


def test_a_position_with_no_screen_left_is_dropped():
    # That monitor is gone: restoring the window there would hide it for good.
    assert sanitized_geometry(1000, 700, 9000, 9000, SCREENS) == WindowGeometry(1000, 700)


def test_a_partially_visible_window_still_counts_as_visible():
    geometry = sanitized_geometry(1000, 700, 1900, 100, SCREENS)

    assert geometry == WindowGeometry(1000, 700, 1900, 100)


def test_without_screen_information_the_position_is_trusted():
    assert sanitized_geometry(1000, 700, 3000, 3000, ()) == WindowGeometry(
        1000, 700, 3000, 3000
    )


def test_the_maximized_flag_survives_sanitizing():
    geometry = sanitized_geometry(1000, 700, 10, 10, SCREENS, maximized=True)

    assert geometry is not None
    assert geometry.maximized is True
    assert sanitized_geometry(0, 0, None, None, SCREENS, maximized=True) is None


def test_capture_and_restore_round_trip(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(1111, 777)
    widget.move(150, 90)

    geometry = capture_geometry(widget)

    restored = QWidget()
    qtbot.addWidget(restored)
    restore_geometry(restored, geometry)

    assert (restored.width(), restored.height()) == (1111, 777)
    assert (restored.x(), restored.y()) == (150, 90)


def test_a_position_is_kept_when_it_lands_on_a_screen():
    assert sanitized_position(560, 560, 120, 80, SCREENS) == (120, 80)


def test_a_position_for_a_fixed_window_with_no_screen_left_is_dropped():
    assert sanitized_position(560, 560, 9000, 9000, SCREENS) is None


def test_a_position_without_screen_information_is_trusted():
    assert sanitized_position(560, 560, 3000, 3000, ()) == (3000, 3000)


def test_a_missing_half_of_the_position_drops_it():
    assert sanitized_position(560, 560, None, 40, SCREENS) is None
    assert sanitized_position(560, 560, 40, None, SCREENS) is None


def test_a_window_without_a_size_gets_no_position():
    assert sanitized_position(0, 0, 40, 40, SCREENS) is None


def test_a_fixed_window_restores_only_the_position(qtbot):
    # A fixed-size window cannot be resized, so the saved size is ignored.
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setFixedSize(300, 200)
    widget.move(150, 90)

    restore_geometry(widget, WindowGeometry(999, 999, 150, 90), size=False)

    assert (widget.width(), widget.height()) == (300, 200)
    assert (widget.x(), widget.y()) == (150, 90)
