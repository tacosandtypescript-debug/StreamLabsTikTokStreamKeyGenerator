"""PySide6 application for preparing a TikTok RTMP session through Streamlabs."""

from __future__ import annotations

import logging
import os
import platform
import sys

from PySide6.QtWidgets import QApplication

from local_token import LocalTokenUnsupportedError
from logging_setup import configure_logging
from ui.main_window import StreamApp
from ui.theme import apply_theme
from version import __version__

LOGGER = logging.getLogger(__name__)

# Re-exported for forks that imported them from this module.
__all__ = ["LocalTokenUnsupportedError", "StreamApp"]


def main() -> int:
    """Configure logging, start Qt and run the application."""

    log_path = configure_logging(os.environ.get("STREAMLABS_KEYGEN_LOG_LEVEL", "WARNING"))
    LOGGER.info(
        "Starting version %s on %s %s (log: %s)",
        __version__,
        platform.system(),
        platform.release(),
        log_path,
    )
    app = QApplication(sys.argv)
    apply_theme(app)
    window = StreamApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
