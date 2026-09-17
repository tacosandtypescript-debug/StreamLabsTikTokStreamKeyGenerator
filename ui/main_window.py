"""The main window of the application."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
)

import avatar as avatar_store
from config_store import (
    ActiveSession,
    AppConfig,
    ConfigError,
    ConfigLoadResult,
    ConfigStore,
    read_config_file,
)
from diagnostics import build_report, default_report_path, system_summary
from errors import safe_error_message
from local_token import find_local_token, local_token_hint
from logging_setup import log_directory, log_file_path
from secure_store import SecureTokenStore, TokenStoreUnavailable
from streamlabs_client import (
    AccountInfo,
    AuthenticationError,
    Category,
    StreamlabsTikTokClient,
    StreamSession,
)
from TokenRetriever import TokenRetrievalError, TokenRetriever
from ui.dialogs import DialogsMixin
from ui.geometry import (
    available_screens,
    capture_geometry,
    restore_geometry,
    sanitized_geometry,
    sanitized_position,
)
from ui.shortcuts import install_shortcuts
from ui.update_flow import UpdateFlowMixin
from ui.window_ui import WindowUiMixin
from workers import Worker

LOGGER = logging.getLogger(__name__)


def _widget_is_alive(widget: Any) -> bool:
    """Return whether the C++ side of ``widget`` still exists.

    A deferred callback or a queued worker signal can outlive its window when Qt
    destroys the widget without a close event, and touching a deleted widget then
    aborts the process instead of raising a normal Python error.
    """

    try:
        from shiboken6 import Shiboken
    except ImportError:  # pragma: no cover - shiboken ships with PySide6
        return True
    try:
        return bool(Shiboken.isValid(widget))
    except TypeError:  # pragma: no cover - not a wrapped object
        return True


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
        # When the account was last confirmed, so the banner can say how old the
        # validation is.
        self._validated_at: datetime | None = None
        # Last account name seen, to draw its initial before Streamlabs answers.
        self._last_username = ""
        # Whether Streamlabs lets this account pick the adult audience.
        self._audience_controls_available = True
        self._category_id = ""
        self._active_session: StreamSession | None = None
        self._session_record: ActiveSession | None = None
        self._session_prompted = False
        self._closing = False
        # Set while the window waits for a stream to end, so that closing can
        # continue once the request has settled.
        self._closing_after_end = False
        self._shortcuts: list[Any] = []
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
        self._shortcuts = install_shortcuts(self)
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

        def run() -> None:
            self._deferred_timers.discard(timer)
            # A hidden window is either not shown yet or already closed. Qt does
            # not deliver a close event for a widget that is not visible, so the
            # timers may still be armed while its deletion is pending; running a
            # modal dialog then outlives the window and crashes.
            if self._closing or not _widget_is_alive(self) or not self.isVisible():
                LOGGER.debug("Dropped a deferred callback for a window that is gone")
                return
            callback()

        timer.timeout.connect(run)
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
            # A saved token means the account page is not what the user came for.
            self.show_stream_page()
            self.refresh_account_info(silent=True)
        else:
            # First run: without a token there is nothing to prepare yet, so the
            # account page is where the work starts.
            self.show_account_page()

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

        self._show_username(config.last_username)
        self._apply_avatar_picture()
        self._restore_window_geometry(config)

    def _restore_window_geometry(self, config: AppConfig) -> None:
        """Give the window back the position it had last time.

        The window is fixed-size, so only the position is restored: its size
        comes from its own content.
        """

        screens = available_screens()
        if self._has_fixed_size():
            position = sanitized_position(
                self.width(),
                self.height(),
                config.window_x,
                config.window_y,
                screens,
            )
            if position is not None:
                self.move(*position)
            return

        geometry = sanitized_geometry(
            config.window_width,
            config.window_height,
            config.window_x,
            config.window_y,
            screens,
            config.window_maximized,
        )
        if geometry is None:
            return
        restore_geometry(self, geometry)

    def _has_fixed_size(self) -> bool:
        """Return whether the window cannot be resized at all."""

        minimum = self.minimumSize()
        return minimum.width() > 0 and minimum == self.maximumSize()

    def _config_from_ui(self) -> AppConfig:
        geometry = capture_geometry(self)
        return AppConfig(
            title=self.stream_title.text().strip(),
            game=self.game_category.text().strip(),
            audience_type="1" if self.mature_checkbox.isChecked() else "0",
            suppress_donation_reminder=self.suppress_donation_reminder,
            legacy_migration_declined=self._legacy_migration_declined,
            active_session=self._session_record,
            window_width=geometry.width,
            window_height=geometry.height,
            window_x=geometry.x,
            window_y=geometry.y,
            window_maximized=geometry.maximized,
            last_username=self._last_username,
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
        visible = self.token_entry.echoMode() == QLineEdit.EchoMode.Normal
        self.token_entry.setEchoMode(
            QLineEdit.EchoMode.Password if visible else QLineEdit.EchoMode.Normal
        )
        self._set_token_reveal_button(not visible)

    def handle_token_change(self) -> None:
        if self._loading_config:
            return
        self._validated_token = None
        self._validated_at = None
        self._account_info = None
        self._category_id = ""
        self._set_suggestions_visible(False)
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
            offer_token_renewal=not silent,
        )

    def _account_loaded(self, token: str, info: AccountInfo) -> None:
        if token != self.token_entry.text().strip():
            return
        self._validated_token = token
        self._validated_at = datetime.now()
        self._account_info = info
        self._show_username(info.username)
        self._apply_audience_controls(info)
        self._set_can_go_live(info.can_be_live)
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
        self._validated_at = None
        self._show_username("")
        self._set_can_go_live(None)
        self._set_status(safe_error_message(exc))
        self._update_controls()
        if not silent:
            QMessageBox.critical(self, "Error de cuenta", safe_error_message(exc))

    def _handle_token_renewal_choice(self, choice: str) -> None:
        """React to the answer given about renewing an expired token.

        Kept separate from the dialog so it can be tested without widgets.
        """

        if choice != "renew":
            LOGGER.info("Token renewal declined by the user")
            self._set_status("El token ha caducado; vuelve a cargarlo")
            return
        LOGGER.info("Token renewal started from the expiry notice")
        self.fetch_online_token()

    def load_local_token(self) -> None:
        self._set_operation_busy("local", True)
        self.load_local_btn.setText("Buscando…")

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
            self._set_suggestions_visible(False)
            self._update_controls()
            return

        if text.strip().casefold() == "other":
            self._category_id = ""
            self._set_suggestions_visible(False)
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
        self._set_suggestions_visible(False)
        self._set_status(safe_error_message(exc))
        self._update_controls()

    def update_suggestions_list(self, categories: list[Category]) -> None:
        self.suggestions_list.clear()
        for category in categories:
            item = QListWidgetItem(category.full_name)
            item.setData(Qt.ItemDataRole.UserRole, category.game_mask_id)
            self.suggestions_list.addItem(item)
        self._set_suggestions_visible(bool(categories))

    def handle_suggestion_selected(self, item: QListWidgetItem) -> None:
        self._category_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self.game_category.setText(item.text())
        self._set_suggestions_visible(False)
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
        if not self._closing_after_end:
            return
        if self._ask_abandon_failed_end():
            self._close_after_end()
        else:
            # The user chose to stay: the session record is intact, so it can be
            # closed from the button or from the next run.
            self._closing_after_end = False

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
        self._close_after_end()

    def copy_to_clipboard(self, field: Any, sensitive: bool) -> None:
        value = field.text()
        if not value:
            return
        QApplication.clipboard().setText(value)
        if sensitive:
            self._clipboard_value = value
            self._clipboard_timer.start()
        # The button confirms in place: a modal dialog per copy was two extra
        # clicks for something that happens several times before every stream.
        flash = getattr(field, "flash_copied", None)
        if callable(flash):
            flash()
        self._set_status(
            "Clave copiada; se retira del portapapeles en 60 segundos"
            if sensitive
            else "URL copiada al portapapeles"
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
        offer_token_renewal: bool = True,
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
                if self._closing or not _widget_is_alive(self):
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
            if offer_token_renewal and isinstance(exc, AuthenticationError):
                # A rejected token has exactly one useful answer, so the generic
                # "something went wrong" message is replaced by the offer to sign
                # in again.
                self._prompt_token_renewal()
                return
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
        self.mature_checkbox.setEnabled(editable and self._audience_controls_available)
        self.go_live_btn.setEnabled(editable and self._can_start_stream())
        self.end_live_btn.setEnabled(session_active and not stream_busy)
        self.refresh_btn.setEnabled(not account_busy and not token_busy)
        self.load_local_btn.setEnabled(not token_busy and not account_busy)
        self.load_online_btn.setEnabled(not token_busy and not account_busy)
        self.save_token_btn.setEnabled(bool(self._validated_token))

        # One place keeps the two "how are we doing" indicators honest: the bar
        # that spins while something is happening and the banner that says in
        # which state the application is.
        self.progress.set_busy(bool(self._busy_operations))
        self._sync_account_summary()
        self._refresh_banner()

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
        # The status bar is one line: an error message with a blank line in it
        # would otherwise make the bar grow to three lines.
        self.app_status.setText(" ".join(text.split()))

    # ------------------------------------------------------------------ #
    #  State shown to the user                                            #
    # ------------------------------------------------------------------ #

    def _show_username(self, username: str) -> None:
        """Show the account name and its initial wherever the account appears."""

        self._last_username = username.strip()
        self.tiktok_username.setText(self._last_username)
        for label in (self.avatar, self.avatar_big):
            label.set_username(self._last_username)

    def _apply_avatar_picture(self) -> None:
        """Put the chosen picture, if there is one, on every avatar."""

        picture = avatar_store.load_avatar()
        for label in (self.avatar, self.avatar_big):
            label.set_picture(picture)
        self.remove_avatar_btn.setEnabled(picture is not None)

    def choose_avatar(self) -> None:
        """Let the user pick a picture: there is none to download.

        Streamlabs does not publish an avatar for the authorised account and
        TikTok only serves one to a browser, so the picture has to be the user's.
        """

        selected, _filters = QFileDialog.getOpenFileName(
            self,
            "Elegir una imagen para la cuenta",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not selected:
            return
        try:
            avatar_store.save_avatar(Path(selected))
        except avatar_store.AvatarError as exc:
            LOGGER.warning("The chosen picture was rejected: %s", type(exc).__name__)
            QMessageBox.warning(self, "Imagen de la cuenta", str(exc))
            return
        self._apply_avatar_picture()
        LOGGER.info("The user changed the account picture")
        self._set_status("Imagen de la cuenta actualizada")

    def remove_avatar(self) -> None:
        """Forget the chosen picture and go back to the drawn initial."""

        avatar_store.remove_avatar()
        self._apply_avatar_picture()
        self._set_status("Imagen de la cuenta quitada")

    def _apply_audience_controls(self, info: AccountInfo) -> None:
        """Use the audience options Streamlabs reports for this account.

        The label stays in Spanish, but whether the option exists at all is
        Streamlabs' answer rather than an assumption: an account whose audience
        controls are disabled must not be offered adult content.
        """

        self._audience_controls_available = not info.audience_controls_disabled
        label = info.audience_label(1)
        if not self._audience_controls_available:
            self.mature_checkbox.setToolTip("Tu cuenta no puede usar contenido para adultos.")
            if self.mature_checkbox.isChecked():
                self.mature_checkbox.setChecked(False)
            return
        note = f"Etiqueta de Streamlabs: «{label}»." if label else ""
        self.mature_checkbox.setToolTip(f"Marca la sesión como contenido para adultos. {note}")

    def _set_can_go_live(self, can: bool | None) -> None:
        """Show the live permission as a badge instead of a raw boolean.

        It used to print ``True``: a Python value, in English, in the middle of a
        Spanish interface.
        """

        if can is None:
            text, state = "—", "neutral"
        else:
            text, state = ("Sí" if can else "No"), ("ok" if can else "error")
        if text == self.can_go_live.text() and state == self.can_go_live.property("state"):
            return
        self.can_go_live.setText(text)
        self.can_go_live.setProperty("state", state)
        self.can_go_live.style().unpolish(self.can_go_live)
        self.can_go_live.style().polish(self.can_go_live)

    def _sync_account_summary(self) -> None:
        """Say on the button who the account belongs to, without opening it."""

        if self._account_info is not None and self._validated_token:
            summary = f"@{self._account_info.username}"
        elif self.token_entry.text().strip():
            summary = "token sin validar"
        else:
            summary = "sin token"
        self.account_btn.setText(f"Cuenta y token · {summary}")

    @staticmethod
    def _session_start_time(record: ActiveSession) -> str:
        """Return the local start time of a recorded session, or an empty string."""

        try:
            started = datetime.fromisoformat(record.started_at)
        except (TypeError, ValueError):
            return ""
        return started.astimezone().strftime("%H:%M")

    @staticmethod
    def _status_date(value: str | None) -> str:
        """Return a short local date for the approval timestamp, or an empty string."""

        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return ""
        try:
            return parsed.astimezone().strftime("%d/%m/%Y")
        except (OverflowError, OSError):  # pragma: no cover - absurd timestamps
            return ""

    def _refresh_banner(self) -> None:
        """Put the state of the application into one sentence."""

        if self._active_session is not None:
            detail = "Copia la URL y la clave en OBS para empezar a emitir."
            if self._session_record is not None:
                started = self._session_start_time(self._session_record)
                if started:
                    detail = f"Sesión abierta desde las {started}. {detail}"
            self._set_banner("live", "Directo preparado", detail)
            return

        token = self.token_entry.text().strip()
        if not token:
            self._set_banner(
                "neutral",
                "Sin token de Streamlabs",
                "Carga el token y valida la cuenta para poder preparar el directo.",
            )
            return

        info = self._account_info
        if info is None or self._validated_token != token:
            self._set_banner(
                "warn",
                "Cuenta sin validar",
                "Pulsa «Actualizar datos de la cuenta» para comprobar el permiso de emisión.",
            )
            return

        detail = f"@{info.username} · {info.application_status}"
        approved = self._status_date(info.status_timestamp)
        if approved:
            detail += f" · aprobado el {approved}"
        if self._validated_at is not None:
            detail += f" · validado a las {self._validated_at.strftime('%H:%M')}"
        if not info.can_be_live:
            self._set_banner(
                "error",
                "Sin permiso para emitir",
                f"{detail}. Esta cuenta no tiene acceso a TikTok LIVE vía Streamlabs.",
            )
            return
        self._set_banner("ok", "Listo para preparar el directo", f"{detail}.")

    def open_donation_page(self) -> None:
        """Open the original author's donation page."""

        QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))

    @staticmethod

    def _safe_error_message(exc: Exception) -> str:
        """Deprecated alias for :func:`errors.safe_error_message`."""

        return safe_error_message(exc)

    def _show_donation_and_schedule_update(self) -> None:
        if self._closing:
            return
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

    def export_diagnostics(self) -> None:
        """Write a redacted report the user can attach to an issue.

        The current token and stream key are handed over only so that they can be
        scrubbed out of the log copy: they must never reach the archive.
        """

        destination = default_report_path()
        try:
            report = build_report(
                destination,
                summary=system_summary(),
                log_path=log_file_path(),
                secret_values=(self.token_entry.text().strip(), self.stream_key.text()),
            )
        except OSError as exc:
            LOGGER.warning("Diagnostics export failed: %s", type(exc).__name__)
            QMessageBox.warning(
                self,
                "Diagnóstico",
                f"No se pudo crear el informe en:\n{destination}\n\n{exc}",
            )
            return

        LOGGER.info("Diagnostics report written to %s", report)
        self._set_status("Informe de diagnóstico guardado")

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Diagnóstico")
        message.setText(
            f"Informe guardado en:\n{report}\n\n"
            "No incluye el token ni la clave de retransmisión. Adjúntalo en la "
            "incidencia de GitHub para que se pueda revisar."
        )
        open_btn = message.addButton("Abrir la carpeta", QMessageBox.ButtonRole.AcceptRole)
        message.addButton(QMessageBox.StandardButton.Ok)
        message.exec()
        if message.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(report).parent)))

    def open_live_monitor(self) -> None:
        QDesktopServices.openUrl(QUrl("https://livecenter.tiktok.com/live_monitor?lang=en-US"))

    def handle_ui_update(self) -> None:
        self.refresh_account_info(silent=True)

    def closeEvent(self, event: Any) -> None:
        # Any deferred callback (the donation notice, the update check) must be
        # stopped before anything else: if the user then cancels the close, a
        # queued call would still be able to run against a half-torn window.
        self._stop_deferred_work()
        if self._active_session is not None and not self._closing_after_end:
            self._handle_close_choice(self._ask_close_with_active_session(), event)
            return
        self._teardown_and_accept(event)

    def _handle_close_choice(self, choice: str, event: Any) -> None:
        """Apply the decision taken when closing with a live session.

        Kept separate from the dialog so every branch can be tested without
        touching modal widgets.
        """

        if choice == "end":
            if self._busy_operations & {"start", "end"} or not self._validated_token:
                self._set_status("Espera a que termine la operación en curso")
                event.ignore()
                return
            # Closing has to wait for the network call, which needs the window
            # (and its token) to still be alive to report what happened.
            self._closing_after_end = True
            self.end_stream()
            event.ignore()
            return
        if choice == "cancel":
            event.ignore()
            return
        # "keep": the session identifier stays on disk, so the next run offers to
        # close it again.
        self._teardown_and_accept(event)

    def _stop_deferred_work(self) -> None:
        """Stop every callback that was scheduled to run later."""

        for timer in list(self._deferred_timers):
            try:
                timer.stop()
            except RuntimeError:  # pragma: no cover - already destroyed
                pass
        self._deferred_timers.clear()

    def _teardown_and_accept(self, event: Any) -> None:
        # From here on, worker callbacks and deferred work must not touch the
        # widgets: Qt may deliver queued calls while the window is destroyed.
        self._closing = True
        # A pending browser login would otherwise keep a pool thread waiting for
        # up to five minutes and delay process shutdown.
        if self._online_retriever is not None:
            self._online_retriever.cancel()
        self._stop_deferred_work()
        self.thread_pool.clear()
        self._clear_sensitive_clipboard()
        event.accept()

    def _close_after_end(self) -> None:
        """Close the window once the end-of-stream request has settled."""

        if not self._closing_after_end:
            return
        self._closing_after_end = False
        self.close()
