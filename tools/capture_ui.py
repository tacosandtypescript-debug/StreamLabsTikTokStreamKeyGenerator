"""Render the real window to PNG files, without showing it on screen.

This is not a mock-up: it builds the actual ``StreamApp``, populates it through the
same methods the running program uses, lets Qt lay everything out, and grabs the
pixels Qt itself painted. What comes out is therefore exactly what the window
shows.

    python tools/capture_ui.py [output-directory]

Both themes and both pages are captured. The window is rendered with Qt's
``offscreen`` platform plugin, so it never appears on the desktop and can run on a
machine with no display at all.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Must be set before QApplication exists: it decides which platform plugin Qt
# loads, and it cannot be changed afterwards.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import profile as profile_store  # noqa: E402

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import StreamApp  # noqa: E402
from ui.theme import DARK, LIGHT, apply_theme  # noqa: E402
from ui.window_ui import PAGE_ACCOUNT, PAGE_STREAM  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs" / "ui"

# Sample content, so the capture shows a filled-in window rather than an empty one.
SAMPLE_TITLE = "Charla de código y café"
SAMPLE_CATEGORY = "Just Chatting"
SAMPLE_URL = "rtmp://push.tiktok.com/live/"
SAMPLE_KEY = "abcd-1234-efgh-5678"
SAMPLE_PROFILE = profile_store.Profile(
    username="estudio_dev",
    display_name="Estudio Dev",
    followers="12.4K",
    likes="98.1K",
    bio="Directos entre semana · código, café y preguntas",
)


def _load_system_fonts(qapp: QApplication) -> str:
    """Load the desktop's own fonts and return the family to use.

    Qt's ``offscreen`` plugin has no font provider of its own, so with it the
    application draws every glyph as an empty box and the capture would be
    unreadable. The fonts are registered from the system directory and the same
    family the desktop would use is made the default, so the capture shows the
    typography the real window has.
    """

    fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    candidates = (
        "segoeui.ttf",  # regular
        "segoeuib.ttf",  # bold
        "segoeuisl.ttf",  # semilight
        "segoeuii.ttf",  # italic
        "seguisb.ttf",  # semibold
        "segoeuil.ttf",  # light
        "segoeuiz.ttf",  # bold italic
        "tahoma.ttf",
        "arial.ttf",
        "arialbd.ttf",
        "seguisym.ttf",
        "seguiemj.ttf",
    )
    for name in candidates:
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))

    available = QFontDatabase.families()
    for family in ("Segoe UI", "Tahoma", "Arial", "Calibri", "Verdana"):
        if family in available:
            qapp.setFont(QFont(family, 9))
            return family
    return qapp.font().family()


def _make_app() -> StreamApp:
    """Build the real window, wired to a throwaway configuration file."""

    import tempfile

    from config_store import ConfigStore
    from secure_store import SecureTokenStore

    workspace = Path(tempfile.mkdtemp(prefix="capture-ui-"))
    window = StreamApp(
        config_store=ConfigStore(workspace / "config.json"),
        token_store=SecureTokenStore(),
    )
    window.resize(window.width(), window.height())
    return window


def _fill(window: StreamApp) -> None:
    """Put the sample content in, using the application's own code paths."""

    window.stream_title.setText(SAMPLE_TITLE)
    window.game_category.setText(SAMPLE_CATEGORY)
    window.mature_checkbox.setChecked(False)
    window.stream_url.setText(SAMPLE_URL)
    window.stream_key.setText(SAMPLE_KEY)

    window._last_username = SAMPLE_PROFILE.username
    window._profile = SAMPLE_PROFILE
    window._refresh_profile_card()
    window._show_username(SAMPLE_PROFILE.username)
    window.can_go_live.setText("Sí")
    window.can_go_live.setProperty("state", "ok")
    window.account_state.setText("La cuenta está validada y puede emitir.")
    window._update_controls()


def _settle(qapp: QApplication, window: StreamApp, rounds: int = 8) -> None:
    """Let every deferred Qt call run, so the window reaches its final state.

    The application finishes its startup on a zero-delay timer, and that timer is
    what decides which page is on screen first. Choosing a page before it runs
    would simply be undone by it, so the queue is drained first.

    Switching page also starts the fade that brings the new one in. That animation
    needs a running clock, which an offscreen capture does not have, so the page
    would be caught half faded and the capture would come out blank. The fade is
    therefore finished by hand before anything is grabbed.
    """

    for _ in range(rounds):
        qapp.processEvents()

    effect = window.pages.currentWidget().graphicsEffect()
    if effect is not None:
        effect.setOpacity(1.0)
    qapp.processEvents()


def _grab(widget, path: Path) -> Path:
    """Save the window exactly as it draws itself, with no padding around it.

    ``widget.grab()`` renders the widget into a pixmap of its own size, which the
    offscreen platform fills correctly. Grabbing the screen instead would add
    whatever empty desktop surrounds the window, and the window's own ``render()``
    must be avoided: the pages carry a ``QGraphicsOpacityEffect`` for the fade
    between them, and rendering a widget that has one maps its children through the
    effect's offscreen pixmap, which shifts the layout sideways.
    """

    image = widget.grab()
    if image is None or image.isNull():  # pragma: no cover - no platform at all
        raise RuntimeError("the window could not be drawn")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), "PNG")
    return path


def capture(output: Path, screen_height: int | None = None) -> list[Path]:
    """Capture every theme and page, and return the files that were written.

    ``screen_height`` stands in for the height of the display. Qt's offscreen
    platform reports a small fixed screen, and the window deliberately never opens
    taller than the screen allows, so without this the capture would show a
    scrollbar that the real desktop does not have.
    """

    written: list[Path] = []
    qapp = QApplication.instance() or QApplication(sys.argv)
    family = _load_system_fonts(qapp)
    print(f"fonts: {family}")

    if screen_height:
        # Patched on the class, before any window exists: the window takes the
        # measurement that counts as it is shown, so an instance attribute set
        # afterwards would arrive too late and change nothing.
        from ui.window_ui import WindowUiMixin

        WindowUiMixin.available_height = lambda self: screen_height

    for theme in (LIGHT, DARK):
        apply_theme(qapp, theme)
        window = _make_app()
        _fill(window)

        # Let Qt finish polishing fonts, wrapping labels and running the geometry
        # pass, so the capture is of a settled window and not a half-built one.
        window.show()
        _settle(qapp, window)

        for index, name in ((PAGE_STREAM, "directo"), (PAGE_ACCOUNT, "cuenta")):
            if index == PAGE_STREAM:
                window.show_stream_page()
            else:
                window.show_account_page()
            _settle(qapp, window)
            written.append(_grab(window, output / f"{name}-{theme}.png"))

        window.close()
        window.deleteLater()
        qapp.processEvents()

    return written


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    output = Path(arguments[0]).resolve() if arguments else DEFAULT_OUTPUT
    height = int(arguments[1]) if len(arguments) > 1 else None

    for path in capture(output, height):
        print(f"captured {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
