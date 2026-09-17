"""Update check, download and installation flow."""

from __future__ import annotations

import logging
import platform
import tempfile
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from errors import safe_error_message
from i18n import tr
from runtime import is_frozen, program_path
from Updater import (
    DownloadCancelled,
    VersionChecker,
    can_self_install,
    default_download_dir,
    download_asset,
    fetch_checksum,
    launch_detached,
    select_asset,
    write_installer_helper,
)

LOGGER = logging.getLogger(__name__)


class UpdateFlowMixin:
    def check_updates_on_startup(self) -> None:
        self._run_worker(
            VersionChecker.check_update,
            self._show_update_if_available,
            lambda exc: LOGGER.debug("Update check failed: %s", type(exc).__name__),
            operation="update-check",
        )

    def _show_update_if_available(self, update_info: dict[str, Any] | None) -> None:
        if not update_info:
            return

        system = platform.system()
        asset = select_asset(
            update_info.get("assets") or [],
            system,
            platform.machine(),
        )
        can_install = self._can_install_update(asset, system)
        version_note = tr(
            "La versión {latest} está disponible (tienes la {current})."
        ).format(latest=update_info["latest"], current=update_info["current"])

        message = QMessageBox(self)
        message.setWindowTitle(tr("Actualización disponible"))
        if can_install:
            message.setText(
                f"{version_note}\n\n"
                + tr(
                    "Puedes instalarla ahora: se descargará, se comprobará su checksum "
                    "y la aplicación se cerrará para actualizarse y volver a abrirse.\n\n"
                    "O descarga el instalador y ejecútalo tú cuando quieras."
                )
            )
        else:
            message.setText(
                f"{version_note}\n\n"
                + tr(
                    "Se guardará en tu carpeta de descargas y se comprobará su checksum. "
                    "La aplicación no ejecuta ni instala nada por su cuenta."
                )
            )

        install_btn = None
        if can_install:
            install_btn = message.addButton(
                tr("Instalar ahora"),
                QMessageBox.ButtonRole.AcceptRole,
            )
        download_btn = message.addButton(tr("Descargar"), QMessageBox.ButtonRole.AcceptRole)
        page_btn = message.addButton(
            tr("Abrir la página del release"),
            QMessageBox.ButtonRole.ActionRole,
        )
        message.addButton(tr("Ahora no"), QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(install_btn or download_btn)
        message.exec()
        clicked = message.clickedButton()

        if install_btn is not None and clicked is install_btn:
            self._download_update(update_info, install=True)
        elif clicked is download_btn:
            self._download_update(update_info, install=False)
        elif clicked is page_btn:
            QDesktopServices.openUrl(QUrl(str(update_info["url"])))

    def _can_install_update(self, asset: dict[str, Any] | None, system: str) -> bool:
        """Return whether the application may replace itself with ``asset``.

        Never while a session is open: the application has to stay alive until
        Streamlabs confirms the session ended, or the session is left behind.
        """

        if self._active_session is not None:
            return False
        return can_self_install(system, asset)

    def _download_update(self, update_info: dict[str, Any], *, install: bool = False) -> None:
        """Download the release package for this platform and verify it."""

        asset = select_asset(
            update_info.get("assets") or [],
            platform.system(),
            platform.machine(),
        )
        if asset is None:
            LOGGER.warning("No release asset matches this platform")
            QMessageBox.warning(
                self,
                "Actualización",
                "Esta release no incluye un paquete para tu sistema. Se abrirá la "
                "página del release para que lo elijas a mano.",
            )
            QDesktopServices.openUrl(QUrl(str(update_info["url"])))
            return

        asset_name = str(asset["name"])
        destination = default_download_dir() / asset_name
        checksums_url = update_info.get("checksums_url")
        self._download_cancel = threading.Event()
        self._set_operation_busy("download", True)
        LOGGER.info("Downloading update asset %s", asset_name)

        progress = QProgressDialog(
            f"Descargando {asset_name}…",
            "Cancelar",
            0,
            100,
            self,
        )
        progress.setWindowTitle("Actualización")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._download_cancel.set)

        def report(done_bytes: int, total_bytes: int) -> None:
            if total_bytes > 0:
                progress.setValue(min(100, int(done_bytes * 100 / total_bytes)))
            else:
                progress.setLabelText(
                    f"Descargando {asset_name}… ({done_bytes // 1048576} MB)"
                )

        def work(progress=None) -> Path:
            expected = None
            if checksums_url:
                expected = fetch_checksum(str(checksums_url), asset_name)
                if expected is None:
                    LOGGER.warning("The release published no checksum for this asset")
            return download_asset(
                str(asset["url"]),
                destination,
                expected_sha256=expected,
                on_progress=progress,
                cancel=self._download_cancel,
            )

        def done(path: Path) -> None:
            progress.close()
            LOGGER.info("Update downloaded to %s", path)
            if install:
                self._launch_installer(Path(path))
                return
            QMessageBox.information(
                self,
                tr("Actualización descargada"),
                tr(
                    "Guardada en:\n{path}\n\n"
                    "El checksum se ha verificado. Cierra esta aplicación y ejecuta el "
                    "archivo cuando quieras: no se instala nada automáticamente."
                ).format(path=path),
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

        def failed(exc: Exception) -> None:
            progress.close()
            if isinstance(exc, DownloadCancelled):
                self._set_status("Descarga cancelada")
                return
            LOGGER.warning("Update download failed: %s", type(exc).__name__)
            QMessageBox.critical(self, "Actualización", safe_error_message(exc))

        self._run_worker(
            work,
            done,
            failed,
            lambda: self._set_operation_busy("download", False),
            on_progress=report,
            operation="update-download",
        )

    def _launch_installer(self, installer: Path) -> None:
        """Start the downloaded installer and quit so it can replace us.

        The installer cannot overwrite a running application, so a detached
        helper waits for this process to disappear, runs it and starts the new
        version afterwards.
        """

        log_path = installer.parent / "actualizacion.log"
        try:
            helper = write_installer_helper(
                Path(tempfile.mkdtemp(prefix="streamlabs-keygen-update-")),
                installer=installer,
                app_executable=program_path() if is_frozen() else None,
                log_path=log_path,
            )
            launch_detached(helper)
        except OSError as exc:
            LOGGER.warning("The update could not be started: %s", type(exc).__name__)
            QMessageBox.warning(
                self,
                tr("Actualización"),
                tr(
                    "No se pudo iniciar el instalador. Ejecútalo a mano desde:\n{path}\n\n{error}"
                ).format(path=installer, error=safe_error_message(exc)),
            )
            return

        LOGGER.info("Installer started; closing so it can replace the application")
        self.close()
