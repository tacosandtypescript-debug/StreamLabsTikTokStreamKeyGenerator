"""The main window of the application."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidgetItem, QMainWindow, QMessageBox

from config_store import (
    ActiveSession,
    AppConfig,
    ConfigError,
    ConfigLoadResult,
    ConfigStore,
    read_config_file,
)
from errors import safe_error_message
from local_token import find_local_token, local_token_hint
from logging_setup import log_directory, log_file_path
from secure_store import SecureTokenStore, TokenStoreUnavailable
from streamlabs_client import AccountInfo, Category, StreamlabsTikTokClient, StreamSession
from TokenRetriever import TokenRetrievalError, TokenRetriever
from ui.dialogs import DialogsMixin
from ui.update_flow import UpdateFlowMixin
from ui.window_ui import WindowUiMixin
from workers import Worker

LOGGER = logging.getLogger(__name__)


class StreamApp(WindowUiMixin, DialogsMixin, UpdateFlowMixin, QMainWindow):
    def __init__(
        self,
        *,
        config_store: ConfigStore | None = None,
        token_store: SecureTokenStore | None = None,
    ) -> None:
        super().__init__()
        self.thread_pool = QThreadPool(self)
        # Injection points: tests pass a temporary configuration store and a
        # fake keyring backend instead of touching the real user environment.
        self.config_store = config_store or ConfigStore()
        self.token_store = token_store or SecureTokenStore()
        self.config = AppConfig()
        self.suppress_donation_reminder = False
        self._loading_config = False
        self._secure_store_available = True
        self._legacy_migration_declined = False
        self._online_retriever: TokenRetriever | None = None
        self._pending_legacy: tuple[Path, ConfigLoadResult] | None = None
        self._account_info: AccountInfo | None = None
        self._validated_token: str | None = None
        self._category_id = ""
        self._active_session: StreamSession | None = None
        self._session_record: ActiveSession | None = None
        self._session_prompted = False
        self._closing = False
        self._deferred_timers: set[QTimer] = set()
        # Qt does not keep the Python object of a QRunnable alive while the pool
        # runs it, so the application must hold a reference itself.
        self._workers: set[Worker] = set()
        self._download_cancel = threading.Event()
        self._busy_operations: set[str] = set()
        self._search_serial = 0
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._start_debounced_search)
        self._pending_search: tuple[str, int] | None = None
        self._clipboard_value: str | None = None
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setSingleShot(True)
        self._clipboard_timer.setInterval(60_000)
        self._clipboard_timer.timeout.connect(self._clear_sensitive_clipboard)

        self.init_ui()
        self.load_config()
        self._defer(0, self._finish_startup)

    def _defer(self, milliseconds: int, callback: Callable[[], None]) -> None:
        """Run ``callback`` later, tied to the lifetime of this window.

        ``QTimer.singleShot`` keeps the callback alive even after the window is
        destroyed, which then runs against deleted C++ objects. A timer
        parented to the window is destroyed together with it.
        """

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(milliseconds)
        timer.timeout.connect(callback)
        timer.timeout.connect(lambda: self._deferred_timers.discard(timer))
        self._deferred_timers.add(timer)
        timer.start()

    def load_config(self) -> None:
        try:
            result = self.config_store.load()
        except ConfigError as exc:
            LOGGER.warning("Configuration could not be loaded: %s", type(exc).__name__)
            result = ConfigLoadResult(config=AppConfig())
            self._defer(
                0,
                lambda: QMessageBox.warning(
                    self,
                    "Aviso de configuración",
                    "No se pudo leer la configuración existente. No se ha sobrescrito.",
                ),
            )

        self.config = result.config
        self._apply_config(result.config)
        self._session_record = result.config.active_session

        # Files written by older versions may still hold a plaintext token, so
        # they are inspected even when a current configuration already exists.
        legacy_path = Path.cwd() / "config.json"
        if (
            legacy_path.exists()
            and legacy_path.resolve() != self.config_store.path.resolve()
            and not self._legacy_migration_declined
        ):
            try:
                legacy_result = read_config_file(legacy_path)
            except ConfigError:
                legacy_result = None
            if legacy_result and legacy_result.had_legacy_token:
                self._pending_legacy = (legacy_path, legacy_result)

        if result.needs_upgrade:
            # Preferences only; rewriting can never touch a token.
            try:
                self.config_store.save(result.config)
            except ConfigError:
                LOGGER.debug("Configuration upgrade could not be persisted", exc_info=True)

        try:
            token = self.token_store.get_token()
        except TokenStoreUnavailable:
            self._secure_store_available = False
            token = None

        if token:
            self._set_token(token)
        elif not self._secure_store_available:
            self._set_status("Almacén seguro no disponible")

    def _finish_startup(self) -> None:
        if self._pending_legacy:
            self._prompt_legacy_migration()
        elif self.token_entry.text():
            self.refresh_account_info(silent=True)

        self._check_pending_session()
        self._defer(3000, self._show_donation_and_schedule_update)

    # ------------------------------------------------------------------ #
    #  Sessions left behind by an earlier run                             #
    # ------------------------------------------------------------------ #

    def _check_pending_session(self) -> None:
        """Warn about a Streamlabs session that a previous run never closed."""

        if self._session_record is None or self._session_prompted:
            return
        if not self.token_entry.text().strip():
            self._set_status("Hay una sesión anterior sin cerrar; carga un token para cerrarla")
            return
        self._prompt_pending_session()

    def _handle_pending_session_choice(self, choice: str) -> None:
        """Apply the decision about a session recorded by an earlier run.

        Kept separate from the dialog so it can be tested without widgets.
        """

        if choice == "forget":
            self._forget_session_record()
            return
        if choice != "close":
            self._set_status("Sesión anterior pendiente de cerrar")
            return

        token = self._validated_token
        if not token:
            self._session_prompted = False
            self._set_status("Valida el token para poder cerrar la sesión anterior")
            return
        self._close_recorded_session(token)

    def _forget_session_record(self) -> None:
        self._session_record = None
        self.save_config(False)
        LOGGER.info("Recorded Streamlabs session discarded by the user")
        self._set_status("Registro de sesión descartado")

    def _close_recorded_session(self, token: str) -> None:
        record = self._session_record
        if record is None:
            return
        session_id = record.session_id
        self._set_operation_busy("end", True)

        def work() -> None:
            StreamlabsTikTokClient(token).end_stream(session_id)

        def done(_: Any = None) -> None:
            self._session_record = None
            self._active_session = None
            self.save_config(False)
            self._update_controls()
            LOGGER.info("Leftover Streamlabs session closed")
            QMessageBox.information(
                self,
                "Sesión anterior",
                "La sesión anterior se cerró correctamente.",
            )

        def failed(exc: Exception) -> None:
            # Streamlabs no longer knows about it, so the record is stale.
            self._session_record = None
            self.save_config(False)
            self._update_controls()
            LOGGER.warning("Leftover session could not be closed: %s", type(exc).__name__)
            QMessageBox.warning(
                self,
                "Sesión anterior",
                f"{safe_error_message(exc)}\n\nSe ha descartado el registro.",
            )

        self._run_worker(
            work,
            done,
            failed,
            lambda: self._set_operation_busy("end", False),
            operation="pending-session-close",
        )

    def _apply_config(self, config: AppConfig) -> None:
        self._loading_config = True
        try:
            self.stream_title.setText(config.title)
            self.game_category.setText(config.game)
            self.mature_checkbox.setChecked(config.audience_type == "1")
            self.suppress_donation_reminder = config.suppress_donation_reminder
            self._legacy_migration_declined = config.legacy_migration_declined
        finally:
            self._loading_config = False

    def _config_from_ui(self) -> AppConfig:
        return AppConfig(
            title=self.stream_title.text().strip(),
            game=self.game_category.text().strip(),
            audience_type="1" if self.mature_checkbox.isChecked() else "0",
            suppress_donation_reminder=self.suppress_donation_reminder,
            legacy_migration_declined=self._legacy_migration_declined,
            active_session=self._session_record,
        )

    def save_config(self, show_message: bool = True) -> bool:
        config = self._config_from_ui()
        try:
            self.config_store.save(config)
        except ConfigError as exc:
            LOGGER.warning("Configuration save failed: %s", type(exc).__name__)
            QMessageBox.critical(self, "Error de configuración", str(exc))
            return False

        self.config = config
        if show_message:
            QMessageBox.information(
                self,
                "Configuración guardada",
                "La configuración se guardó sin incluir el token.",
            )
        return True

    def save_token_securely(self) -> None:
        token = self.token_entry.text().strip()
        if not token:
            QMessageBox.warning(self, "Token", "Primero introduce o carga un token.")
            return
        if token != self._validated_token:
            QMessageBox.warning(
                self,
                "Token no validado",
                "Actualiza la información de la cuenta antes de guardar el token.",
            )
            return
        try:
            self.token_store.save_token(token)
            self._secure_store_available = True
        except TokenStoreUnavailable as exc:
            self._secure_store_available = False
            QMessageBox.warning(self, "Almacén seguro", str(exc))
            return
        QMessageBox.information(
            self,
            "Token guardado",
            "El token se guardó en el almacén seguro del sistema.",
        )

    def toggle_token_visibility(self) -> None:
        if self.token_entry.echoMode() == QLineEdit.EchoMode.Normal:
            self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_token_btn.setText("👁️")
            self.toggle_token_btn.setToolTip("Mostrar el token")
        else:
            self.token_entry.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_token_btn.setText("👁️‍🗨️")
            self.toggle_token_btn.setToolTip("Ocultar el token")

    def handle_token_change(self) -> None:
        if self._loading_config:
            return
        self._validated_token = None
        self._account_info = None
        self._category_id = ""
        self.suggestions_list.hide()
        self._set_status("Token pendiente de validar" if self.token_entry.text() else "Sin token")
        self._update_controls()

    def refresh_account_info(self, silent: bool = False) -> None:
        token = self.token_entry.text().strip()
        if not token:
            if not silent:
                QMessageBox.warning(self, "Token", "Introduce o carga un token primero.")
            return

        self._account_info = None
        self._validated_token = None
        self._category_id = ""
        self._set_status("Validando token…")
        self._set_operation_busy("account", True)

        def work() -> AccountInfo:
            return StreamlabsTikTokClient(token).get_account_info()

        self._run_worker(
            work,
            lambda info: self._account_loaded(token, info),
            lambda exc: self._account_failed(token, exc, silent),
            lambda: self._set_operation_busy("account", False),
            operation="account-validation",
        )

    def _account_loaded(self, token: str, info: AccountInfo) -> None:
        if token != self.token_entry.text().strip():
            return
        self._validated_token = token
        self._account_info = info
        self.tiktok_username.setText(info.username)
        self.app_status.setText(info.application_status)
        self.can_go_live.setText(str(info.can_be_live))
        self._set_status("Cuenta validada" if info.can_be_live else "Sin permiso para emitir")
        LOGGER.info("Account validated: %s (can_be_live=%s)", info.username, info.can_be_live)
        self._update_controls()
        if self._session_record is not None and not self._session_prompted:
            self._prompt_pending_session()
        if self.game_category.text().strip():
            self.fetch_game_mask_id(self.game_category.text().strip())

    def _account_failed(self, token: str, exc: Exception, silent: bool) -> None:
        if token != self.token_entry.text().strip():
            return
        LOGGER.warning("Account validation failed: %s", type(exc).__name__)
        self._account_info = None
        self._validated_token = None
        self.tiktok_username.clear()
        self.app_status.clear()
        self.can_go_live.clear()
        self._set_status(safe_error_message(exc))
        self._update_controls()
        if not silent:
            QMessageBox.critical(self, "Error de cuenta", safe_error_message(exc))

    def load_local_token(self) -> None:
        self._set_operation_busy("local", True)
        self.load_local_btn.setText("Searching…")

        self._run_worker(
            find_local_token,
            self._local_token_loaded,
            lambda exc: QMessageBox.warning(
                self,
                "Token local",
                safe_error_message(exc),
            ),
            lambda: (
                self._set_operation_busy("local", False),
                self.load_local_btn.setText("Cargar desde el PC"),
            ),
            operation="token-local",
        )

    @staticmethod

    def _find_local_token() -> str | None:
        """Deprecated alias for :func:`local_token.find_local_token`."""

        return find_local_token()

    def _local_token_loaded(self, token: str | None) -> None:
        if not token:
            QMessageBox.warning(self, "Token local", local_token_hint())
            return
        LOGGER.info("Token read from the Streamlabs local storage")
        self._apply_retrieved_token(token)

    def fetch_online_token(self) -> None:
        self._set_operation_busy("online", True)
        self.load_online_btn.setText("Esperando el inicio de sesión…")

        retriever = TokenRetriever()
        self._online_retriever = retriever

        def work() -> str:
            token = retriever.retrieve_token()
            if not token:
                raise TokenRetrievalError("No se pudo obtener un token mediante el login web.")
            return token

        def finished() -> None:
            self._online_retriever = None
            self._set_operation_busy("online", False)
            self.load_online_btn.setText("Iniciar sesión web")

        self._run_worker(
            work,
            self._apply_retrieved_token,
            lambda exc: QMessageBox.critical(
                self,
                "Inicio de sesión web",
                safe_error_message(exc),
            ),
            finished,
            operation="token-web",
        )

    def _apply_retrieved_token(self, token: str) -> None:
        self.token_entry.setText(token)
        self._set_status("Token obtenido; validando…")
        self.refresh_account_info(silent=True)

    def handle_game_search(self, text: str) -> None:
        if self._loading_config:
            return
        self._search_serial += 1
        serial = self._search_serial
        self._category_id = ""
        if not text.strip() or not self._validated_token:
            self._pending_search = None
            self._search_timer.stop()
            self.suggestions_list.hide()
            self._update_controls()
            return

        if text.strip().casefold() == "other":
            self._category_id = ""
            self.suggestions_list.hide()
            self._update_controls()
            return

        self._pending_search = (text, serial)
        self._search_timer.start()
        self._update_controls()

    def _start_debounced_search(self) -> None:
        if not self._pending_search:
            return
        query, serial = self._pending_search
        self._run_category_search(query, serial, show_suggestions=True)

    def fetch_game_mask_id(self, game_name: str) -> None:
        if not game_name.strip() or not self._validated_token:
            self._category_id = ""
            self._update_controls()
            return
        self._search_serial += 1
        self._run_category_search(game_name, self._search_serial, show_suggestions=False)

    def _run_category_search(self, query: str, serial: int, show_suggestions: bool) -> None:
        token = self._validated_token
        if not token:
            return
        # A unique key per search keeps an older, slower request from clearing
        # the busy flag of the newer one.
        operation = f"search-{serial}"
        self._set_operation_busy(operation, True)

        def work() -> tuple[str, int, list[Category]]:
            categories = StreamlabsTikTokClient(token).search_categories(query)
            return query, serial, categories

        self._run_worker(
            work,
            lambda result: self._categories_loaded(result, show_suggestions),
            lambda exc: self._category_search_failed(serial, exc),
            lambda: self._set_operation_busy(operation, False),
            operation=f"category-search-{serial}",
        )

    def _categories_loaded(
        self,
        result: tuple[str, int, list[Category]],
        show_suggestions: bool,
    ) -> None:
        query, serial, categories = result
        if serial != self._search_serial or query != self.game_category.text():
            return

        selected_id = ""
        for category in categories:
            if category.full_name == query:
                selected_id = category.game_mask_id
                break
        self._category_id = selected_id
        if show_suggestions:
            self.update_suggestions_list(categories)
        self._update_controls()

    def _category_search_failed(self, serial: int, exc: Exception) -> None:
        if serial != self._search_serial:
            return
        self.suggestions_list.hide()
        self._set_status(safe_error_message(exc))
        self._update_controls()

    def update_suggestions_list(self, categories: list[Category]) -> None:
        self.suggestions_list.clear()
        for category in categories:
            item = QListWidgetItem(category.full_name)
            item.setData(Qt.ItemDataRole.UserRole, category.game_mask_id)
            self.suggestions_list.addItem(item)
        self.suggestions_list.setVisible(bool(categories))

    def handle_suggestion_selected(self, item: QListWidgetItem) -> None:
        self._category_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self.game_category.setText(item.text())
        self.suggestions_list.hide()
        self._update_controls()

    def start_stream(self) -> None:
        if not self._can_start_stream():
            QMessageBox.warning(
                self,
                "Directo no preparado",
                "Valida la cuenta y selecciona una categoría válida antes de iniciar.",
            )
            return

        token = self._validated_token
        title = self.stream_title.text().strip()
        category_id = self._category_id
        audience_type = "1" if self.mature_checkbox.isChecked() else "0"
        assert token is not None
        self._set_operation_busy("start", True)
        self._set_status("Iniciando sesión de Streamlabs…")

        def work() -> StreamSession:
            return StreamlabsTikTokClient(token).start_stream(
                title,
                category_id,
                audience_type,
            )

        self._run_worker(
            work,
            self._stream_started,
            lambda exc: QMessageBox.critical(
                self,
                "Preparar directo",
                safe_error_message(exc),
            ),
            lambda: self._set_operation_busy("start", False),
            operation="stream-start",
        )

    def _stream_started(self, session: StreamSession) -> None:
        self._active_session = session
        # Persist the session id: if the application or the machine dies now,
        # the next run can offer to close the session it left behind.
        self._session_record = ActiveSession(
            session_id=session.session_id,
            title=self.stream_title.text().strip(),
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._session_prompted = True
        self.save_config(False)
        LOGGER.info("Streamlabs session started")
        self.stream_url.setText(session.rtmp_url)
        self.stream_key.setText(session.stream_key)
        self._set_status("Sesión preparada; configura OBS")
        self._update_controls()
        QMessageBox.information(
            self,
            "Directo preparado",
            "Sesión preparada. Copia la URL y la clave de retransmisión en OBS para comenzar.",
        )

    def end_stream(self) -> None:
        if not self._active_session or not self._validated_token:
            return
        token = self._validated_token
        session_id = self._active_session.session_id
        self._set_operation_busy("end", True)
        self._set_status("Finalizando sesión de Streamlabs…")

        def work() -> None:
            StreamlabsTikTokClient(token).end_stream(session_id)

        self._run_worker(
            work,
            self._stream_ended,
            self._stream_end_failed,
            lambda: self._set_operation_busy("end", False),
            operation="stream-end",
        )

    def _stream_end_failed(self, exc: Exception) -> None:
        self._set_status("No se pudo confirmar el cierre; puedes reintentarlo")
        QMessageBox.critical(
            self,
            "Finalizar directo",
            f"{safe_error_message(exc)}\n\n"
            "La sesión se conserva localmente. Pulsa «Finalizar directo» otra vez "
            "o abre «Registros» si el problema continúa.",
        )

    def _stream_ended(self, _: Any = None) -> None:
        self._active_session = None
        self._session_record = None
        self.save_config(False)
        LOGGER.info("Streamlabs session ended")
        self.stream_url.clear()
        self.stream_key.clear()
        self._set_status("Cuenta validada")
        self._update_controls()
        QMessageBox.information(
            self,
            "Directo finalizado",
            "La sesión de Streamlabs terminó correctamente.",
        )

    def copy_to_clipboard(self, widget: QLineEdit, sensitive: bool) -> None:
        value = widget.text()
        if not value:
            return
        QApplication.clipboard().setText(value)
        if sensitive:
            self._clipboard_value = value
            self._clipboard_timer.start()
        QMessageBox.information(
            self,
            "Copiado",
            "Copiado. La clave de retransmisión se retirará del portapapeles en 60 segundos."
            if sensitive
            else "Texto copiado al portapapeles.",
        )

    def _clear_sensitive_clipboard(self) -> None:
        self._clipboard_timer.stop()
        clipboard = QApplication.clipboard()
        if self._clipboard_value and clipboard.text() == self._clipboard_value:
            clipboard.clear()
        self._clipboard_value = None

    def _handle_legacy_choice(
        self,
        choice: str,
        legacy_path: Path,
        result: ConfigLoadResult,
    ) -> None:
        """Apply the decision about a legacy plaintext token.

        Kept separate from the dialog so the security-relevant behaviour (a
        plaintext token is never loaded unless the user asked for it) can be
        tested without touching modal widgets.
        """

        token = result.legacy_token
        if choice == "delete":
            self._delete_legacy_file(legacy_path)
            self.token_entry.clear()
            LOGGER.info("Legacy plaintext configuration deleted")
            self._set_status("Token antiguo eliminado")
            return

        if choice != "import" or not token:
            # The decision is remembered so the prompt does not come back on
            # every launch.
            self._remember_declined_migration()
            LOGGER.info("Legacy plaintext token left in place at user request")
            self._set_status("Token antiguo no importado")
            return

        try:
            self.token_store.save_token(token)
            self._secure_store_available = True
        except TokenStoreUnavailable as exc:
            QMessageBox.warning(self, "Migración", safe_error_message(exc))
            self._remember_declined_migration()
            LOGGER.warning("Legacy token could not be stored securely")
        else:
            self._rewrite_legacy_without_token(legacy_path, result.config)
            self.save_config(False)
            LOGGER.info("Legacy plaintext token migrated to the credential store")

        self._set_token(token)
        self.refresh_account_info(silent=True)

    def _remember_declined_migration(self) -> None:
        self._legacy_migration_declined = True
        self.save_config(False)

    def _rewrite_legacy_without_token(self, legacy_path: Path, config: AppConfig) -> None:
        try:
            ConfigStore.migrate_legacy_file(legacy_path, config)
        except ConfigError:
            LOGGER.warning("Could not rewrite the legacy configuration file")

    def _delete_legacy_file(self, legacy_path: Path) -> None:
        try:
            legacy_path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not delete the legacy configuration file")
            QMessageBox.warning(
                self,
                "Migración",
                "No se pudo borrar el fichero antiguo. Elimínalo manualmente.",
            )

    def _run_worker(
        self,
        function: Callable[[], Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[Exception], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        *,
        operation: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        worker = Worker(function)
        self._workers.add(worker)
        operation_name = operation or getattr(function, "__name__", "background-operation")
        LOGGER.info("Background operation started: %s", operation_name)
        # A queued connection is required here: these callbacks are plain
        # functions and lambdas with no thread affinity, so Qt would otherwise
        # invoke them directly on the worker thread and touch the GUI from it.
        queued = Qt.ConnectionType.QueuedConnection

        def guard(callback: Callable[..., None]) -> Callable[..., None]:
            """Never run a worker callback against a closed window.

            A queued call can still be delivered while the window is being
            destroyed, and touching its widgets then crashes the process.
            """

            def wrapped(*args: Any) -> None:
                if self._closing:
                    LOGGER.debug("Dropped a worker callback after close")
                    return
                callback(*args)

            return wrapped

        if on_progress is not None:
            # Worker forwards keyword arguments to the callable, so the long
            # running function receives a reporter bound to the queued progress
            # signal: the dialog is only ever touched from the GUI thread.
            worker.kwargs["progress"] = worker.signals.progress.emit
            worker.signals.progress.connect(guard(on_progress), queued)

        def handle_result(*args: Any) -> None:
            LOGGER.info("Background operation completed: %s", operation_name)
            on_result(*args)

        worker.signals.result.connect(guard(handle_result), queued)

        def handle_error(exc: Exception) -> None:
            LOGGER.warning(
                "Background operation failed: %s (%s): %s",
                operation_name,
                type(exc).__name__,
                safe_error_message(exc),
            )
            if on_error:
                on_error(exc)
            else:
                QMessageBox.critical(self, "Error", safe_error_message(exc))

        worker.signals.error.connect(guard(handle_error), queued)
        if on_finished:
            worker.signals.finished.connect(guard(on_finished), queued)
        worker.signals.finished.connect(guard(lambda: self._workers.discard(worker)), queued)
        self.thread_pool.start(worker)

    def _set_operation_busy(self, operation: str, busy: bool) -> None:
        if busy:
            self._busy_operations.add(operation)
        else:
            self._busy_operations.discard(operation)
        self._update_controls()

    def _update_controls(self) -> None:
        account_can_live = bool(
            self._account_info
            and self._validated_token
            and self._validated_token == self.token_entry.text().strip()
            and self._account_info.can_be_live
        )
        session_active = self._active_session is not None
        stream_busy = bool(self._busy_operations & {"start", "end"})
        account_busy = "account" in self._busy_operations
        token_busy = bool(self._busy_operations & {"local", "online"})

        editable = account_can_live and not session_active and not stream_busy
        self.stream_title.setEnabled(editable)
        self.game_category.setEnabled(editable)
        self.mature_checkbox.setEnabled(editable)
        self.go_live_btn.setEnabled(editable and self._can_start_stream())
        self.end_live_btn.setEnabled(session_active and not stream_busy)
        self.refresh_btn.setEnabled(not account_busy and not token_busy)
        self.load_local_btn.setEnabled(not token_busy and not account_busy)
        self.load_online_btn.setEnabled(not token_busy and not account_busy)
        self.save_token_btn.setEnabled(bool(self._validated_token))

    def _can_start_stream(self) -> bool:
        if self._active_session or self._busy_operations & {"start", "end", "account"}:
            return False
        if not self._account_info or not self._account_info.can_be_live:
            return False
        if not self._validated_token or self._validated_token != self.token_entry.text().strip():
            return False
        if not self.stream_title.text().strip() or not self.game_category.text().strip():
            return False
        category = self.game_category.text().strip().casefold()
        return category == "other" or bool(self._category_id)

    def _set_token(self, token: str) -> None:
        self._loading_config = True
        try:
            self.token_entry.setText(token)
        finally:
            self._loading_config = False
        self._validated_token = None
        self._account_info = None
        self._category_id = ""
        self._update_controls()

    def _set_status(self, text: str) -> None:
        self.app_status.setText(text)

    @staticmethod

    def _safe_error_message(exc: Exception) -> str:
        """Deprecated alias for :func:`errors.safe_error_message`."""

        return safe_error_message(exc)

    def _show_donation_and_schedule_update(self) -> None:
        self.show_donation_reminder()
        self._defer(3000, self.check_updates_on_startup)

    def open_logs_folder(self) -> None:
        """Open the folder that holds the application log file."""

        directory = log_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Registros",
                f"No se pudo abrir la carpeta de registros: {exc}",
            )
            return
        LOGGER.debug("Opening %s (log file %s)", directory, log_file_path())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def open_live_monitor(self) -> None:
        QDesktopServices.openUrl(QUrl("https://livecenter.tiktok.com/live_monitor?lang=en-US"))

    def handle_ui_update(self) -> None:
        self.refresh_account_info(silent=True)

    def closeEvent(self, event: Any) -> None:
        # From here on, worker callbacks and deferred work must not touch the
        # widgets: Qt may deliver queued calls while the window is destroyed.
        self._closing = True
        if self._active_session:
            QMessageBox.warning(
                self,
                "Sesión activa",
                "La sesión de Streamlabs sigue activa. Comprueba OBS antes de cerrar.\n\n"
                "Se ha guardado su identificador: al volver a abrir la aplicación "
                "podrás cerrarla desde ahí.",
            )
        # A pending browser login would otherwise keep a pool thread waiting for
        # up to five minutes and delay process shutdown.
        if self._online_retriever is not None:
            self._online_retriever.cancel()
        # Deferred work must not run against a closed window.
        for timer in list(self._deferred_timers):
            try:
                timer.stop()
            except RuntimeError:  # pragma: no cover - already destroyed
                pass
        self._deferred_timers.clear()
        self.thread_pool.clear()
        self._clear_sensitive_clipboard()
        event.accept()
