"""Update check, download and installation flow."""

from __future__ import annotations

import logging
import platform
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from errors import safe_error_message
from Updater import (
    DownloadCancelled,
    VersionChecker,
    default_download_dir,
    download_asset,
    fetch_checksum,
    select_asset,
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
        message = QMessageBox(self)
        message.setWindowTitle("Actualización disponible")
        message.setText(
            f"La versión {update_info['latest']} está disponible "
            f"(tienes la {update_info['current']}).\n\n"
            "Puedes descargarla desde aquí: se guardará en tu carpeta de descargas y "
            "se comprobará su checksum. La aplicación no ejecuta ni instala nada."
        )
        download_btn = message.addButton("Descargar", QMessageBox.ButtonRole.AcceptRole)
        page_btn = message.addButton(
            "Abrir la página del release", QMessageBox.ButtonRole.ActionRole
        )
        message.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(download_btn)
        message.exec()
        clicked = message.clickedButton()

        if clicked is download_btn:
            self._download_update(update_info)
        elif clicked is page_btn:
            QDesktopServices.openUrl(QUrl(str(update_info["url"])))

    def _download_update(self, update_info: dict[str, Any]) -> None:
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
            QMessageBox.information(
                self,
                "Actualización descargada",
                f"Guardada en:\n{path}\n\n"
                "El checksum se ha verificado. Cierra esta aplicación y ejecuta el "
                "archivo cuando quieras: no se instala nada automáticamente.",
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
