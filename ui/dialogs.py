"""Modal dialogs shown by the main window."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QMessageBox


class DialogsMixin:
    def _prompt_pending_session(self) -> None:
        record = self._session_record
        if record is None:
            return
        self._session_prompted = True

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Sesión anterior sin cerrar")
        message.setText(
            "La aplicación se cerró con una sesión de Streamlabs sin terminar.\n\n"
            f"Título: {record.title or '(sin título)'}\n"
            f"Iniciada: {record.started_at or 'fecha desconocida'}\n\n"
            "Si esa sesión sigue abierta, TikTok puede rechazar un nuevo directo. "
            "¿Quieres cerrarla ahora?"
        )
        close_btn = message.addButton("Cerrar la sesión", QMessageBox.ButtonRole.AcceptRole)
        forget_btn = message.addButton(
            "Olvidar el registro", QMessageBox.ButtonRole.DestructiveRole
        )
        message.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(close_btn)
        message.exec()
        clicked = message.clickedButton()

        if clicked is forget_btn:
            choice = "forget"
        elif clicked is close_btn:
            choice = "close"
        else:
            choice = "later"
        self._handle_pending_session_choice(choice)

    def _prompt_legacy_migration(self) -> None:
        """Ask what to do with a plaintext token found in an old config file."""

        if not self._pending_legacy:
            return
        legacy_path, result = self._pending_legacy
        self._pending_legacy = None
        if not result.legacy_token:
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Token antiguo")
        message.setText(
            "Se encontró un token antiguo guardado en texto plano en:\n"
            f"{legacy_path}\n\n"
            "Cualquier programa puede leer ese fichero. ¿Qué quieres hacer?"
        )
        import_btn = message.addButton(
            "Importar al almacén seguro", QMessageBox.ButtonRole.AcceptRole
        )
        delete_btn = message.addButton(
            "Borrar el fichero antiguo", QMessageBox.ButtonRole.DestructiveRole
        )
        message.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(import_btn)
        message.exec()
        clicked = message.clickedButton()

        if clicked is delete_btn:
            choice = "delete"
        elif clicked is import_btn:
            choice = "import"
        else:
            # "Ahora no", Escape, or the window close button.
            choice = "decline"
        self._handle_legacy_choice(choice, legacy_path, result)

    def show_donation_reminder(self) -> None:
        if self.suppress_donation_reminder:
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Apoya el proyecto")
        message.setText(
            "¿Te resulta útil esta aplicación? Puedes apoyar su desarrollo."
        )
        dont_show_again = QCheckBox("No volver a mostrar este mensaje")
        message.setCheckBox(dont_show_again)
        donate_btn = message.addButton("Donar ahora", QMessageBox.ButtonRole.AcceptRole)
        message.addButton(QMessageBox.StandardButton.Ok)
        donate_btn.setStyleSheet("font-weight: bold;")
        message.exec()

        if dont_show_again.isChecked():
            self.suppress_donation_reminder = True
            self.save_config(False)
        if message.clickedButton() == donate_btn:
            QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))

    def show_help(self) -> None:
        help_text = (
            "1. Solicita el acceso a TikTok LIVE/RTMP a través de Streamlabs.\n"
            "2. Carga el token con «Iniciar sesión web» o «Cargar desde el PC».\n"
            "3. Pulsa «Actualizar datos de la cuenta» y elige título y categoría.\n"
            "4. Opcional: «Guardar token de forma segura» para no repetir el login.\n"
            "5. Pulsa «Preparar directo» y copia la URL y la clave en OBS.\n"
            "6. Al terminar, pulsa «Finalizar directo»."
        )
        QMessageBox.information(self, "Ayuda", help_text)

    def _ask_close_with_active_session(self) -> str:
        """Ask what to do about the session that is still open.

        Returns ``"end"``, ``"keep"`` or ``"cancel"``. The caller applies the
        decision, so the flow can be tested without modal widgets.
        """

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Sesión activa")
        message.setText(
            "La sesión de Streamlabs sigue activa. Si cierras ahora, TikTok puede "
            "rechazar el siguiente directo.\n\n"
            "Detén primero la salida de TikTok en OBS y elige qué hacer."
        )
        end_btn = message.addButton(
            "Finalizar directo y cerrar",
            QMessageBox.ButtonRole.AcceptRole,
        )
        keep_btn = message.addButton(
            "Cerrar sin finalizar",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        message.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(end_btn)
        message.exec()
        clicked = message.clickedButton()

        if clicked is end_btn:
            return "end"
        if clicked is keep_btn:
            return "keep"
        # "Cancelar", Escape or the window close button: change nothing.
        return "cancel"

    def _ask_abandon_failed_end(self) -> bool:
        """Ask whether to close anyway when the session could not be ended."""

        answer = QMessageBox.question(
            self,
            "Sesión sin cerrar",
            "No se pudo cerrar la sesión de Streamlabs.\n\n"
            "¿Quieres cerrar la aplicación igualmente? Su identificador queda "
            "guardado y podrás cerrarla al volver a abrirla.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _prompt_token_renewal(self) -> None:
        """Offer a fresh web login after Streamlabs rejected the token."""

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Token caducado")
        message.setText(
            "Streamlabs ha rechazado el token: no es válido o ha caducado.\n\n"
            "¿Quieres iniciar sesión otra vez para obtener uno nuevo?"
        )
        renew_btn = message.addButton(
            "Iniciar sesión web",
            QMessageBox.ButtonRole.AcceptRole,
        )
        message.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(renew_btn)
        message.exec()
        clicked = message.clickedButton()

        self._handle_token_renewal_choice("renew" if clicked is renew_btn else "later")
