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


def test_the_version_can_be_asked_without_opening_a_window(capsys):
    # A packaged build has to be able to say which version it is: that is how a
    # release is checked after installing it.
    code = entry.main(["--version"])

    printed = capsys.readouterr().out
    assert code == 0
    assert entry.__version__ in printed
    assert "Streamlabs" in printed


def test_the_help_explains_the_two_flags(capsys):
    code = entry.main(["--help"])

    printed = capsys.readouterr().out
    assert code == 0
    assert "--version" in printed
    assert "--check" in printed


def test_the_short_help_flag_works_too(capsys):
    assert entry.main(["-h"]) == 0
    assert "Uso:" in capsys.readouterr().out


def test_the_check_runs_the_self_check(monkeypatch):
    called = []
    monkeypatch.setattr(entry, "run_self_check", lambda: called.append(True) or 0)

    code = entry.main(["--check"])

    assert code == 0
    assert called
