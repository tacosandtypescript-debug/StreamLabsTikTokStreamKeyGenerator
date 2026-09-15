"""PySide6 application for preparing a TikTok RTMP session through Streamlabs."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config_store import (
    ActiveSession,
    AppConfig,
    ConfigError,
    ConfigLoadResult,
    ConfigStore,
    read_config_file,
)
from errors import safe_error_message
from local_token import LocalTokenUnsupportedError, find_local_token, local_token_hint
from logging_setup import configure_logging, log_directory, log_file_path
from secure_store import SecureTokenStore, TokenStoreUnavailable
from streamlabs_client import (
    AccountInfo,
    Category,
    StreamlabsTikTokClient,
    StreamSession,
)
from TokenRetriever import TokenRetrievalError, TokenRetriever
from Updater import (
    DownloadCancelled,
    VersionChecker,
    default_download_dir,
    download_asset,
    fetch_checksum,
    select_asset,
)
from version import __version__
from workers import Worker

LOGGER = logging.getLogger(__name__)

# Re-exported for forks that imported it from this module.
__all__ = ["LocalTokenUnsupportedError", "StreamApp"]


class StreamApp(QMainWindow):
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

    def init_ui(self) -> None:
        self.setWindowTitle("Generador de clave de TikTok Live (vía Streamlabs)")
        self.setMinimumSize(800, 600)

        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        left_column = QVBoxLayout()
        main_layout.addLayout(left_column)

        token_group = QGroupBox("Token de Streamlabs")
        token_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        left_column.addWidget(token_group)
        token_layout = QVBoxLayout(token_group)
        token_layout.setContentsMargins(8, 12, 8, 8)
        token_layout.setSpacing(6)

        token_entry_row = QHBoxLayout()
        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Pega aquí el token o cárgalo con los botones…")
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.setFixedHeight(28)
        self.token_entry.textChanged.connect(lambda _text: self.handle_token_change())
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_entry_row.addWidget(self.token_entry)

        self.toggle_token_btn = QPushButton("👁️")
        self.toggle_token_btn.setFixedSize(28, 28)
        self.toggle_token_btn.setToolTip("Mostrar el token")
        self.toggle_token_btn.clicked.connect(lambda _checked=False: self.toggle_token_visibility())
        token_entry_row.addWidget(self.toggle_token_btn)
        token_layout.addLayout(token_entry_row)

        load_buttons_row = QHBoxLayout()
        self.load_local_btn = QPushButton("Cargar desde el PC")
        self.load_local_btn.setFixedHeight(30)
        self.load_local_btn.setToolTip(
            "Lee el token que Streamlabs Desktop tiene guardado en este equipo"
        )
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons_row.addWidget(self.load_local_btn)

        self.load_online_btn = QPushButton("Iniciar sesión web")
        self.load_online_btn.setFixedHeight(30)
        self.load_online_btn.setToolTip("Obtiene el token con el inicio de sesión de Streamlabs")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons_row.addWidget(self.load_online_btn)
        token_layout.addLayout(load_buttons_row)

        self.save_token_btn = QPushButton("Guardar token de forma segura")
        self.save_token_btn.setFixedHeight(30)
        self.save_token_btn.setToolTip(
            "Guarda el token validado en el almacén de credenciales del sistema"
        )
        self.save_token_btn.clicked.connect(lambda _checked=False: self.save_token_securely())
        token_layout.addWidget(self.save_token_btn)

        account_info_label = QLabel("Información de la cuenta")
        account_info_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        token_layout.addWidget(account_info_label)

        username_row = QHBoxLayout()
        username_label = QLabel("Usuario:")
        username_label.setFixedWidth(100)
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setFixedHeight(26)
        username_row.addWidget(username_label)
        username_row.addWidget(self.tiktok_username)
        token_layout.addLayout(username_row)

        status_row = QHBoxLayout()
        status_label = QLabel("Estado:")
        status_label.setFixedWidth(100)
        self.app_status = QLineEdit()
        self.app_status.setReadOnly(True)
        self.app_status.setFixedHeight(26)
        status_row.addWidget(status_label)
        status_row.addWidget(self.app_status)
        token_layout.addLayout(status_row)

        live_row = QHBoxLayout()
        live_label = QLabel("Puede emitir:")
        live_label.setFixedWidth(100)
        self.can_go_live = QLineEdit()
        self.can_go_live.setReadOnly(True)
        self.can_go_live.setFixedHeight(26)
        live_row.addWidget(live_label)
        live_row.addWidget(self.can_go_live)
        token_layout.addLayout(live_row)

        self.refresh_btn = QPushButton("Actualizar datos de la cuenta")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setToolTip(
            "Vuelve a consultar el usuario, el estado y el permiso de emisión"
        )
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_account_info())
        token_layout.addWidget(self.refresh_btn)
        token_layout.addStretch()

        stream_group = QGroupBox("Datos del directo")
        left_column.addWidget(stream_group)
        stream_layout = QVBoxLayout(stream_group)
        stream_layout.setContentsMargins(8, 8, 8, 8)
        stream_layout.setSpacing(5)

        title_label = QLabel("Título del directo:")
        title_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(title_label)
        self.stream_title = QLineEdit()
        self.stream_title.setFixedHeight(28)
        self.stream_title.textChanged.connect(lambda _text: self._update_controls())
        stream_layout.addWidget(self.stream_title)

        game_label = QLabel("Categoría:")
        game_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(game_label)
        self.game_category = QLineEdit()
        self.game_category.setFixedHeight(28)
        self.game_category.setToolTip("Escribe para buscar; elige una sugerencia de la lista")
        self.game_category.textChanged.connect(self.handle_game_search)
        stream_layout.addWidget(self.game_category)

        self.suggestions_list = QListWidget()
        self.suggestions_list.hide()
        self.suggestions_list.setFixedHeight(100)
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        stream_layout.addWidget(self.suggestions_list)

        self.mature_checkbox = QCheckBox("Contenido para adultos")
        self.mature_checkbox.setStyleSheet("padding: 2px;")
        self.mature_checkbox.stateChanged.connect(lambda _state: self._update_controls())
        stream_layout.addWidget(self.mature_checkbox)
        stream_layout.addStretch()

        control_group = QGroupBox("Control del directo")
        control_group.setMinimumWidth(250)
        main_layout.addWidget(control_group)
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(8, 12, 8, 8)
        control_layout.setSpacing(6)

        button_row = QHBoxLayout()
        self.go_live_btn = QPushButton("Preparar directo")
        self.go_live_btn.setToolTip(
            "Pide a Streamlabs que prepare la sesión y devuelve la URL y la clave"
        )
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.setFixedHeight(32)
        self.go_live_btn.clicked.connect(lambda _checked=False: self.start_stream())
        button_row.addWidget(self.go_live_btn)

        self.end_live_btn = QPushButton("Finalizar directo")
        self.end_live_btn.setToolTip(
            "Detén primero la salida de TikTok en OBS y después cierra la sesión de Streamlabs"
        )
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.setFixedHeight(32)
        self.end_live_btn.clicked.connect(lambda _checked=False: self.end_stream())
        button_row.addWidget(self.end_live_btn)
        control_layout.addLayout(button_row)

        url_label = QLabel("URL del servidor:")
        url_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(url_label)
        self.stream_url = QLineEdit()
        self.stream_url.setReadOnly(True)
        self.stream_url.setFixedHeight(28)
        control_layout.addWidget(self.stream_url)
        self.copy_url_btn = QPushButton("Copiar URL")
        self.copy_url_btn.setFixedHeight(28)
        self.copy_url_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_url, False))
        control_layout.addWidget(self.copy_url_btn)

        key_label = QLabel("Clave de retransmisión:")
        key_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(key_label)
        self.stream_key = QLineEdit()
        self.stream_key.setReadOnly(True)
        self.stream_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.stream_key.setFixedHeight(28)
        control_layout.addWidget(self.stream_key)
        self.copy_key_btn = QPushButton("Copiar clave")
        self.copy_key_btn.setToolTip("Se borra del portapapeles a los 60 segundos")
        self.copy_key_btn.setFixedHeight(28)
        self.copy_key_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_key, True))
        control_layout.addWidget(self.copy_key_btn)
        control_layout.addStretch()

        bottom_buttons = QHBoxLayout()
        left_column.addLayout(bottom_buttons)
        self.save_btn = QPushButton("Guardar configuración")
        self.save_btn.setToolTip("Guarda el título, la categoría y las preferencias (sin secretos)")
        self.save_btn.clicked.connect(lambda _checked=False: self.save_config())
        bottom_buttons.addWidget(self.save_btn)

        self.help_btn = QPushButton("Ayuda")
        self.help_btn.clicked.connect(lambda _checked=False: self.show_help())
        bottom_buttons.addWidget(self.help_btn)

        self.logs_btn = QPushButton("Registros")
        self.logs_btn.setToolTip("Abrir la carpeta de registros de la aplicación")
        self.logs_btn.clicked.connect(lambda _checked=False: self.open_logs_folder())
        bottom_buttons.addWidget(self.logs_btn)

        self.donate_btn = QPushButton("☕ Donar")
        self.donate_btn.setToolTip("Apoyar al autor del proyecto original")
        self.donate_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))
        )
        bottom_buttons.addWidget(self.donate_btn)

        self.monitor_btn = QPushButton("Abrir monitor de TikTok")
        self.monitor_btn.setToolTip("Abre el monitor de directos de TikTok en el navegador")
        self.monitor_btn.clicked.connect(lambda _checked=False: self.open_live_monitor())
        bottom_buttons.addWidget(self.monitor_btn)

        self._set_status("Sin token")

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


if __name__ == "__main__":
    log_path = configure_logging(os.environ.get("STREAMLABS_KEYGEN_LOG_LEVEL", "WARNING"))
    LOGGER.info(
        "Starting version %s on %s %s (log: %s)",
        __version__,
        platform.system(),
        platform.release(),
        log_path,
    )
    app = QApplication(sys.argv)
    window = StreamApp()
    window.show()
    sys.exit(app.exec())
