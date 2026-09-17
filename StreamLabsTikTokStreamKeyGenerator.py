"""PySide6 application for preparing a TikTok RTMP session through Streamlabs.

Besides the window, the program answers two questions a packaged build has to be able
to answer about itself: which version it is (``--version``) and whether it actually
works (``--check``). The second one exists because a bundle can be broken in ways the
source never is.
"""

from __future__ import annotations

import logging
import os
import platform
import sys

from PySide6.QtWidgets import QApplication

from i18n import set_language
from local_token import LocalTokenUnsupportedError
from logging_setup import configure_logging
from selfcheck import run_self_check, say
from ui.main_window import StreamApp
from ui.theme import apply_theme
from version import __version__

LOGGER = logging.getLogger(__name__)

# Re-exported for forks that imported them from this module.
__all__ = ["LocalTokenUnsupportedError", "StreamApp"]

PROGRAM_NAME = "Generador de clave de TikTok Live (vía Streamlabs)"

HELP = f"""{PROGRAM_NAME} {__version__}

Uso: StreamLabsTikTokStreamKeyGenerator [opción]

  --version   Muestra la versión y termina.
  --check     Comprueba que la aplicación empaquetada funciona, sin abrir ventana:
              que Qt cargue, que el icono y las dos pantallas estén, que el tamaño
              sea utilizable y qué fuente de emoji encontró. Termina con 0 si está
              bien y con 1 si algo imprescindible falta.
  --help      Muestra esta ayuda.

Sin ninguna opción, abre la ventana de siempre.
"""


def main(argv: list[str] | None = None) -> int:
    """Configure logging, start Qt and run the application."""

    arguments = list(sys.argv[1:] if argv is None else argv)

    if "--help" in arguments or "-h" in arguments:
        say(HELP)
        return 0
    if "--version" in arguments:
        say(f"{PROGRAM_NAME} {__version__}")
        return 0
    if "--check" in arguments:
        return run_self_check()

    log_path = configure_logging(os.environ.get("STREAMLABS_KEYGEN_LOG_LEVEL", "WARNING"))
    LOGGER.info(
        "Starting version %s on %s %s (log: %s)",
        __version__,
        platform.system(),
        platform.release(),
        log_path,
    )
    app = QApplication(sys.argv)
    set_language()
    apply_theme(app)
    window = StreamApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
