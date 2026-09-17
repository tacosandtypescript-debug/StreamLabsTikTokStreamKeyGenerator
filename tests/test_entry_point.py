"""The entry point and the composition of the main window.

Importing the entry module is the documented way to start the application and
the way forks reach ``StreamApp``, so it is worth pinning down.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

import StreamLabsTikTokStreamKeyGenerator as entry
from ui.dialogs import DialogsMixin
from ui.main_window import StreamApp
from ui.update_flow import UpdateFlowMixin
from ui.window_ui import WindowUiMixin


def test_entry_point_still_exposes_the_documented_names():
    assert entry.__all__ == ["LocalTokenUnsupportedError", "StreamApp"]
    assert entry.StreamApp is StreamApp
    assert callable(entry.main)


def test_the_window_is_composed_from_the_ui_mixins():
    assert issubclass(StreamApp, QMainWindow)
    assert issubclass(StreamApp, WindowUiMixin)
    assert issubclass(StreamApp, DialogsMixin)
    assert issubclass(StreamApp, UpdateFlowMixin)


def test_every_split_module_stands_on_its_own():
    # No circular imports between the pieces of the window.
    assert WindowUiMixin.__module__ == "ui.window_ui"
    assert DialogsMixin.__module__ == "ui.dialogs"
    assert UpdateFlowMixin.__module__ == "ui.update_flow"
    assert StreamApp.__module__ == "ui.main_window"
