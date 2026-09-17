"""Facts about the running interpreter and the build it comes from."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return whether the code runs from a compiled build.

    Nuitka does not use PyInstaller's ``sys.frozen``: it injects
    ``__compiled__`` into the globals of every module it compiles. Both signals
    are checked, and either one is enough, so this stays correct under Nuitka,
    under PyInstaller and when running from a source checkout.
    """

    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def program_path() -> Path:
    """Return the running program: the executable when frozen, else the script."""

    if is_frozen():
        return Path(sys.executable).resolve()
    entry = sys.argv[0] if sys.argv and sys.argv[0] else __file__
    return Path(os.path.abspath(entry))
