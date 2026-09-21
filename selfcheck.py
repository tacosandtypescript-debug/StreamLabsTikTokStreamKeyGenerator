"""A self-check the packaged application can run on its own.

The continuous integration tests the source, and the source was never the problem:
what breaks is the *bundle*. A packaged build can be missing a Qt plugin, an icon,
the whole assets folder or — as happened once — the fonts, and none of that shows up
until a user opens it and finds boxes where the text should be.

So the built application can answer for itself: ``--check`` builds the real window
offscreen, looks at what it got and says whether it is usable. The job that publishes
a release runs it before publishing anything.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from version import __version__

LOGGER = logging.getLogger(__name__)

# Below this the window is not usable, whatever it says about itself.
MINIMUM_USABLE_SIDE = 320


def say(*parts: str) -> None:
    """Write to the console when there is one.

    A packaged Windows build has no console at all, and ``print`` would fail there —
    which is exactly how the first version of this broke continuous integration.
    Printing is a convenience; the report file and the exit code are the contract.
    """

    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(*parts)
    except (OSError, ValueError, AttributeError):  # pragma: no cover - odd consoles
        LOGGER.debug("The console could not be written to", exc_info=True)


@dataclass(frozen=True)
class CheckResult:
    """One thing that was looked at, and what was found."""

    name: str
    ok: bool
    detail: str = ""
    # A failure that means the application is broken for the user, as opposed to a
    # cosmetic surprise worth printing but not worth stopping a release for.
    critical: bool = True


@dataclass
class SelfCheckReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, check: CheckResult) -> None:
        self.results.append(check)

    @property
    def failed(self) -> list[CheckResult]:
        return [item for item in self.results if not item.ok and item.critical]

    @property
    def warnings(self) -> list[CheckResult]:
        return [item for item in self.results if not item.ok and not item.critical]

    @property
    def ok(self) -> bool:
        return not self.failed

    def text(self) -> str:
        lines = [f"Autocomprobación de la versión {__version__}"]
        for item in self.results:
            mark = "OK  " if item.ok else ("FALLO" if item.critical else "aviso")
            detail = f" — {item.detail}" if item.detail else ""
            lines.append(f"  [{mark}] {item.name}{detail}")
        if self.ok:
            lines.append("Resultado: la aplicación puede funcionar.")
        else:
            lines.append(
                "Resultado: " + ", ".join(item.name for item in self.failed) + "."
            )
        for item in self.warnings:
            lines.append(f"  (aviso: {item.name} — {item.detail})")
        return "\n".join(lines)


def _window_facts(window: Any) -> SelfCheckReport:
    """Look at a window that was built for real and report what it is."""

    from PySide6.QtWidgets import QApplication

    from ui.text import emoji_font_name

    report = SelfCheckReport()
    report.add(
        CheckResult(
            "Qt y plataforma",
            True,
            f"{QApplication.platformName()} ({platform.system()} {platform.machine()})",
        )
    )

    icon = window.windowIcon()
    report.add(
        CheckResult(
            "Icono de la aplicación",
            not icon.isNull(),
            f"{len(icon.availableSizes())} tamaños" if not icon.isNull() else "no cargó",
            critical=False,
        )
    )

    width, height = window.width(), window.height()
    report.add(
        CheckResult(
            "Ventana con tamaño utilizable",
            width >= MINIMUM_USABLE_SIDE and height >= MINIMUM_USABLE_SIDE,
            f"{width}x{height}",
        )
    )
    report.add(
        CheckResult(
            "Ventana de tamaño fijo",
            window.minimumSize() == window.maximumSize()
            and window.minimumWidth() >= MINIMUM_USABLE_SIDE,
            f"fijada en {window.width()}x{window.height()}",
        )
    )

    pages = getattr(window, "pages", None)
    report.add(
        CheckResult(
            "Las dos pantallas existen",
            pages is not None and pages.count() == 2,
            f"{pages.count() if pages is not None else 0} pantallas",
        )
    )
    report.add(
        CheckResult(
            "El contenido cabe o se puede desplazar",
            getattr(window, "scroll", None) is not None,
            "área de desplazamiento lista",
        )
    )

    for name, attribute in (
        ("Cabecera de perfil", "account_profile_card"),
        ("Línea de cuenta del directo", "account_avatar"),
        ("Campos del directo", "stream_title"),
        ("Campo del token", "token_entry"),
    ):
        report.add(
            CheckResult(
                f"{name} presentes",
                getattr(window, attribute, None) is not None,
            )
        )

    emoji = emoji_font_name()
    report.add(
        CheckResult(
            "Fuente de emoji",
            True,
            emoji or "ninguna instalada: los emoji se quitan en vez de salir como cuadros",
            critical=False,
        )
    )
    return report


def report_file_path() -> Path:
    """Return where the self-check leaves its report.

    A packaged Windows build has no console, so printing is not enough to prove
    anything: the report is also written next to the logs, where it can be read.
    """

    from logging_setup import log_directory

    return log_directory() / "autocomprobacion.txt"


def _write_report(text: str) -> Path | None:
    """Write the report, and never fail the check because of it."""

    destination = report_file_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    except OSError:
        LOGGER.debug("The self-check report could not be written", exc_info=True)
        return None
    return destination


def run_self_check(
    *,
    window_factory: Callable[[], Any] | None = None,
    output: Callable[[str], None] | None = None,
) -> int:
    """Build the application offscreen, look at it and report. Returns an exit code."""

    tell = say if output is None else output
    # A build that cannot start without a display could never be checked in CI, and
    # the point is to check the build, not the machine it runs on.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from config_store import ConfigStore
    from i18n import set_language
    from ui.main_window import StreamApp
    from ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    set_language()
    apply_theme(app)

    with tempfile.TemporaryDirectory(prefix="autocomprobacion-") as folder:
        # A temporary configuration: a check must not even read the user's settings,
        # let alone change them.
        store = ConfigStore(Path(folder) / "config.json")
        if window_factory is None:
            window = StreamApp(config_store=store)
        else:
            window = window_factory()
        try:
            report = _window_facts(window)
        finally:
            window.hide()
            window.deleteLater()
            app.processEvents()

    text = report.text()
    written = _write_report(text)
    tell(text)
    if written is not None:
        tell(f"Informe guardado en: {written}")
    return 0 if report.ok else 1
