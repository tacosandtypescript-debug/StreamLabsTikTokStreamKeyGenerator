"""Keyboard shortcuts.

They are declared as data instead of being wired one by one so that the list can
be tested, documented and reviewed in one place.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

# (sequence, name of the method on the window that it invokes)
SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+Return", "start_stream"),
    ("Ctrl+Shift+Return", "end_stream"),
    ("Ctrl+D", "export_diagnostics"),
    ("Ctrl+L", "open_logs_folder"),
    ("F1", "show_help"),
)


def install_shortcuts(window: Any) -> list[QShortcut]:
    """Create every shortcut, parented to ``window`` so Qt owns their lifetime.

    The target method is looked up when the shortcut fires, not when it is
    created, so replacing a method on the window (as the tests do) still works.
    """

    installed: list[QShortcut] = []
    for sequence, method_name in SHORTCUTS:
        shortcut = QShortcut(QKeySequence(sequence), window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(lambda name=method_name: getattr(window, name)())
        installed.append(shortcut)
    return installed
