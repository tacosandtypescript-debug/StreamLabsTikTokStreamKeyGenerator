"""PySide6 application for preparing a TikTok RTMP session through Streamlabs."""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
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
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config_store import (
    AppConfig,
    ConfigError,
    ConfigLoadResult,
    ConfigStore,
    read_config_file,
)
from secure_store import SecureTokenStore, TokenStoreUnavailable
from streamlabs_client import (
    AccountInfo,
    Category,
    StreamlabsError,
    StreamlabsTikTokClient,
    StreamSession,
)
from TokenRetriever import TokenRetrievalError, TokenRetriever
from Updater import VersionChecker
from workers import Worker

LOGGER = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(rb'"apiToken"\s*:\s*"([a-f0-9]{16,})"', re.IGNORECASE)
MAX_TOKEN_FILE_BYTES = 25 * 1024 * 1024


class LocalTokenUnsupportedError(RuntimeError):
    """Raised when Streamlabs local data is not available on this OS."""


class StreamApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread_pool = QThreadPool(self)
        self.config_store = ConfigStore()
        self.token_store = SecureTokenStore()
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
        QTimer.singleShot(0, self._finish_startup)

    def init_ui(self) -> None:
        self.setWindowTitle("StreamLabs TikTok Stream Key Generator")
        self.setMinimumSize(800, 600)

        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        left_column = QVBoxLayout()
        main_layout.addLayout(left_column)

        token_group = QGroupBox("Token Loader")
        token_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        left_column.addWidget(token_group)
        token_layout = QVBoxLayout(token_group)
        token_layout.setContentsMargins(8, 12, 8, 8)
        token_layout.setSpacing(6)

        token_entry_row = QHBoxLayout()
        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Paste token here or load below...")
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.setFixedHeight(28)
        self.token_entry.textChanged.connect(lambda _text: self.handle_token_change())
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_entry_row.addWidget(self.token_entry)

        self.toggle_token_btn = QPushButton("👁️")
        self.toggle_token_btn.setFixedSize(28, 28)
        self.toggle_token_btn.setToolTip("Show token")
        self.toggle_token_btn.clicked.connect(lambda _checked=False: self.toggle_token_visibility())
        token_entry_row.addWidget(self.toggle_token_btn)
        token_layout.addLayout(token_entry_row)

        load_buttons_row = QHBoxLayout()
        self.load_local_btn = QPushButton("Load from PC")
        self.load_local_btn.setFixedHeight(30)
        self.load_local_btn.setToolTip("Load a token from Streamlabs Desktop data")
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons_row.addWidget(self.load_local_btn)

        self.load_online_btn = QPushButton("Load from Web")
        self.load_online_btn.setFixedHeight(30)
        self.load_online_btn.setToolTip("Get a token through the Streamlabs browser login")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons_row.addWidget(self.load_online_btn)
        token_layout.addLayout(load_buttons_row)

        self.save_token_btn = QPushButton("Save Token Securely")
        self.save_token_btn.setFixedHeight(30)
        self.save_token_btn.setToolTip("Save the validated token in the OS secure store")
        self.save_token_btn.clicked.connect(lambda _checked=False: self.save_token_securely())
        token_layout.addWidget(self.save_token_btn)

        account_info_label = QLabel("Account Information")
        account_info_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        token_layout.addWidget(account_info_label)

        username_row = QHBoxLayout()
        username_label = QLabel("Username:")
        username_label.setFixedWidth(100)
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setFixedHeight(26)
        username_row.addWidget(username_label)
        username_row.addWidget(self.tiktok_username)
        token_layout.addLayout(username_row)

        status_row = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setFixedWidth(100)
        self.app_status = QLineEdit()
        self.app_status.setReadOnly(True)
        self.app_status.setFixedHeight(26)
        status_row.addWidget(status_label)
        status_row.addWidget(self.app_status)
        token_layout.addLayout(status_row)

        live_row = QHBoxLayout()
        live_label = QLabel("Can Go Live:")
        live_label.setFixedWidth(100)
        self.can_go_live = QLineEdit()
        self.can_go_live.setReadOnly(True)
        self.can_go_live.setFixedHeight(26)
        live_row.addWidget(live_label)
        live_row.addWidget(self.can_go_live)
        token_layout.addLayout(live_row)

        self.refresh_btn = QPushButton("Refresh Account Info")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_account_info())
        token_layout.addWidget(self.refresh_btn)
        token_layout.addStretch()

        stream_group = QGroupBox("Stream Details")
        left_column.addWidget(stream_group)
        stream_layout = QVBoxLayout(stream_group)
        stream_layout.setContentsMargins(8, 8, 8, 8)
        stream_layout.setSpacing(5)

        title_label = QLabel("Stream Title:")
        title_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(title_label)
        self.stream_title = QLineEdit()
        self.stream_title.setFixedHeight(28)
        self.stream_title.textChanged.connect(lambda _text: self._update_controls())
        stream_layout.addWidget(self.stream_title)

        game_label = QLabel("Game Category:")
        game_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(game_label)
        self.game_category = QLineEdit()
        self.game_category.setFixedHeight(28)
        self.game_category.textChanged.connect(self.handle_game_search)
        stream_layout.addWidget(self.game_category)

        self.suggestions_list = QListWidget()
        self.suggestions_list.hide()
        self.suggestions_list.setFixedHeight(100)
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        stream_layout.addWidget(self.suggestions_list)

        self.mature_checkbox = QCheckBox("Enable mature content")
        self.mature_checkbox.setStyleSheet("padding: 2px;")
        self.mature_checkbox.stateChanged.connect(lambda _state: self._update_controls())
        stream_layout.addWidget(self.mature_checkbox)
        stream_layout.addStretch()

        control_group = QGroupBox("Stream Control")
        control_group.setMinimumWidth(250)
        main_layout.addWidget(control_group)
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(8, 12, 8, 8)
        control_layout.setSpacing(6)

        button_row = QHBoxLayout()
        self.go_live_btn = QPushButton("Go Live")
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.setFixedHeight(32)
        self.go_live_btn.clicked.connect(lambda _checked=False: self.start_stream())
        button_row.addWidget(self.go_live_btn)

        self.end_live_btn = QPushButton("End Live")
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.setFixedHeight(32)
        self.end_live_btn.clicked.connect(lambda _checked=False: self.end_stream())
        button_row.addWidget(self.end_live_btn)
        control_layout.addLayout(button_row)

        url_label = QLabel("Stream URL:")
        url_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(url_label)
        self.stream_url = QLineEdit()
        self.stream_url.setReadOnly(True)
        self.stream_url.setFixedHeight(28)
        control_layout.addWidget(self.stream_url)
        self.copy_url_btn = QPushButton("Copy URL")
        self.copy_url_btn.setFixedHeight(28)
        self.copy_url_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_url, False))
        control_layout.addWidget(self.copy_url_btn)

        key_label = QLabel("Stream Key:")
        key_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(key_label)
        self.stream_key = QLineEdit()
        self.stream_key.setReadOnly(True)
        self.stream_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.stream_key.setFixedHeight(28)
        control_layout.addWidget(self.stream_key)
        self.copy_key_btn = QPushButton("Copy Key")
        self.copy_key_btn.setFixedHeight(28)
        self.copy_key_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_key, True))
        control_layout.addWidget(self.copy_key_btn)
        control_layout.addStretch()

        bottom_buttons = QHBoxLayout()
        left_column.addLayout(bottom_buttons)
        self.save_btn = QPushButton("Save Config")
        self.save_btn.setToolTip("Save non-sensitive stream preferences")
        self.save_btn.clicked.connect(lambda _checked=False: self.save_config())
        bottom_buttons.addWidget(self.save_btn)

        self.help_btn = QPushButton("Help")
        self.help_btn.clicked.connect(lambda _checked=False: self.show_help())
        bottom_buttons.addWidget(self.help_btn)

        self.donate_btn = QPushButton("☕ Donate")
        self.donate_btn.setToolTip("Support the developer")
        self.donate_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/loukious"))
        )
        bottom_buttons.addWidget(self.donate_btn)

        self.monitor_btn = QPushButton("Open Live Monitor")
        self.monitor_btn.clicked.connect(lambda _checked=False: self.open_live_monitor())
        bottom_buttons.addWidget(self.monitor_btn)

        self._set_status("Sin token")

    def load_config(self) -> None:
        try:
            result = self.config_store.load()
        except ConfigError as exc:
            LOGGER.warning("Configuration could not be loaded: %s", type(exc).__name__)
            result = ConfigLoadResult(config=AppConfig())
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    self,
                    "Configuration warning",
                    "No se pudo leer la configuración existente. No se ha sobrescrito.",
                ),
            )

        self.config = result.config
        self._apply_config(result.config)

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

        QTimer.singleShot(3000, self._show_donation_and_schedule_update)

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
        )

    def save_config(self, show_message: bool = True) -> bool:
        config = self._config_from_ui()
        try:
            self.config_store.save(config)
        except ConfigError as exc:
            LOGGER.debug("Configuration save failed", exc_info=True)
            QMessageBox.critical(self, "Configuration error", str(exc))
            return False

        self.config = config
        if show_message:
            QMessageBox.information(
                self,
                "Config Saved",
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
            self.toggle_token_btn.setToolTip("Show token")
        else:
            self.token_entry.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_token_btn.setText("👁️‍🗨️")
            self.toggle_token_btn.setToolTip("Hide token")

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
        )

    def _account_loaded(self, token: str, info: AccountInfo) -> None:
        if token != self.token_entry.text().strip():
            return
        self._validated_token = token
        self._account_info = info
        self.tiktok_username.setText(info.username)
        self.app_status.setText(info.application_status)
        self.can_go_live.setText(str(info.can_be_live))
        self._set_status("Cuenta validada" if info.can_be_live else "Sin permiso para Go Live")
        self._update_controls()
        if self.game_category.text().strip():
            self.fetch_game_mask_id(self.game_category.text().strip())

    def _account_failed(self, token: str, exc: Exception, silent: bool) -> None:
        if token != self.token_entry.text().strip():
            return
        self._account_info = None
        self._validated_token = None
        self.tiktok_username.clear()
        self.app_status.clear()
        self.can_go_live.clear()
        self._set_status(self._safe_error_message(exc))
        self._update_controls()
        if not silent:
            QMessageBox.critical(self, "Account error", self._safe_error_message(exc))

    def load_local_token(self) -> None:
        self._set_operation_busy("local", True)
        self.load_local_btn.setText("Searching…")

        self._run_worker(
            self._find_local_token,
            self._local_token_loaded,
            lambda exc: QMessageBox.warning(
                self,
                "Local token",
                self._safe_error_message(exc),
            ),
            lambda: (
                self._set_operation_busy("local", False),
                self.load_local_btn.setText("Load from PC"),
            ),
        )

    @staticmethod
    def _find_local_token() -> str | None:
        if platform.system() == "Windows":
            appdata = os.environ.get("APPDATA")
            if not appdata:
                raise LocalTokenUnsupportedError("No se encontró la carpeta AppData.")
            base = Path(appdata) / "slobs-client" / "Local Storage" / "leveldb"
        elif platform.system() == "Darwin":
            base = (
                Path.home()
                / "Library"
                / "Application Support"
                / "slobs-client"
                / "Local Storage"
                / "leveldb"
            )
        else:
            raise LocalTokenUnsupportedError(
                "La importación local está disponible en Windows y macOS; "
                "usa Login from Web en Linux."
            )

        if not base.is_dir():
            return None

        files = [
            file
            for pattern in ("*.log", "*.ldb")
            for file in base.glob(pattern)
            if file.is_file()
        ]
        files.sort(key=lambda file: file.stat().st_mtime, reverse=True)
        for file in files:
            try:
                if file.stat().st_size > MAX_TOKEN_FILE_BYTES:
                    continue
                content = file.read_bytes()
            except OSError:
                continue
            for match in reversed(TOKEN_PATTERN.findall(content)):
                token = match.decode("ascii", errors="ignore").strip()
                if token:
                    return token
        return None

    def _local_token_loaded(self, token: str | None) -> None:
        if not token:
            QMessageBox.warning(
                self,
                "Local token",
                "No se encontró un token en los datos locales de Streamlabs.",
            )
            return
        self._apply_retrieved_token(token)

    def fetch_online_token(self) -> None:
        self._set_operation_busy("online", True)
        self.load_online_btn.setText("Waiting for login…")

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
            self.load_online_btn.setText("Load from Web")

        self._run_worker(
            work,
            self._apply_retrieved_token,
            lambda exc: QMessageBox.critical(
                self,
                "Web login",
                self._safe_error_message(exc),
            ),
            finished,
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
        self._set_status(self._safe_error_message(exc))
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
                "Stream not ready",
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
                "Start stream",
                self._safe_error_message(exc),
            ),
            lambda: self._set_operation_busy("start", False),
        )

    def _stream_started(self, session: StreamSession) -> None:
        self._active_session = session
        self.stream_url.setText(session.rtmp_url)
        self.stream_key.setText(session.stream_key)
        self._set_status("Sesión preparada; configura OBS")
        self._update_controls()
        QMessageBox.information(
            self,
            "Live Started",
            "Sesión preparada. Copia la URL y la stream key en OBS para comenzar.",
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
            lambda exc: QMessageBox.critical(
                self,
                "End stream",
                self._safe_error_message(exc),
            ),
            lambda: self._set_operation_busy("end", False),
        )

    def _stream_ended(self, _: Any = None) -> None:
        self._active_session = None
        self.stream_url.clear()
        self.stream_key.clear()
        self._set_status("Cuenta validada")
        self._update_controls()
        QMessageBox.information(
            self,
            "Live Ended",
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
            "Copied",
            "Copiado. La stream key se retirará del portapapeles en 60 segundos."
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
        if not self._pending_legacy:
            return
        legacy_path, result = self._pending_legacy
        self._pending_legacy = None
        token = result.legacy_token
        if not token:
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Migrate token")
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
            self._delete_legacy_file(legacy_path)
            self.token_entry.clear()
            self._set_status("Token antiguo eliminado")
            return

        if clicked is not import_btn:
            # "Ahora no", Escape, or closing the dialog: a plaintext token is
            # never loaded unless the user explicitly asked for it, and the
            # decision is remembered so the prompt does not come back.
            self._remember_declined_migration()
            self._set_status("Token antiguo no importado")
            return

        try:
            self.token_store.save_token(token)
            self._secure_store_available = True
        except TokenStoreUnavailable as exc:
            QMessageBox.warning(self, "Migration", self._safe_error_message(exc))
            self._remember_declined_migration()
        else:
            self._rewrite_legacy_without_token(legacy_path, result.config)
            self.save_config(False)

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
                "Migration",
                "No se pudo borrar el fichero antiguo. Elimínalo manualmente.",
            )

    def _run_worker(
        self,
        function: Callable[[], Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[Exception], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        worker = Worker(function)
        # A queued connection is required here: these callbacks are plain
        # functions and lambdas with no thread affinity, so Qt would otherwise
        # invoke them directly on the worker thread and touch the GUI from it.
        queued = Qt.ConnectionType.QueuedConnection
        worker.signals.result.connect(on_result, queued)

        def handle_error(exc: Exception) -> None:
            LOGGER.debug("Background operation failed: %s", type(exc).__name__)
            if on_error:
                on_error(exc)
            else:
                QMessageBox.critical(self, "Error", self._safe_error_message(exc))

        worker.signals.error.connect(handle_error, queued)
        if on_finished:
            worker.signals.finished.connect(on_finished, queued)
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
        if isinstance(
            exc,
            (
                ValueError,
                ConfigError,
                TokenStoreUnavailable,
                TokenRetrievalError,
                StreamlabsError,
                LocalTokenUnsupportedError,
            ),
        ):
            return str(exc)
        return "La operación no pudo completarse. Revisa la conexión y vuelve a intentarlo."

    def _show_donation_and_schedule_update(self) -> None:
        self.show_donation_reminder()
        QTimer.singleShot(3000, self.check_updates_on_startup)

    def show_donation_reminder(self) -> None:
        if self.suppress_donation_reminder:
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Support Development")
        message.setText("Enjoying this app? Consider supporting its development!")
        dont_show_again = QCheckBox("Never show this message again")
        message.setCheckBox(dont_show_again)
        donate_btn = message.addButton("Donate Now", QMessageBox.ButtonRole.AcceptRole)
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
        )

    def _show_update_if_available(self, update_info: dict[str, str] | None) -> None:
        if not update_info:
            return
        message = QMessageBox(self)
        message.setWindowTitle("Update Available")
        message.setText(
            f"Version {update_info['latest']} is available!\n\n"
            f"Current version: {update_info['current']}\n\n"
            "Would you like to open the release page?"
        )
        message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        message.setDefaultButton(QMessageBox.StandardButton.Yes)
        if message.exec() == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(update_info["url"]))

    def show_help(self) -> None:
        help_text = (
            "1. Apply for TikTok LIVE/RTMP access through Streamlabs.\n"
            "2. Use Load from PC or Load from Web.\n"
            "3. Validate the account and select a title/category.\n"
            "4. Optionally save the validated token securely.\n"
            "5. Prepare the session, then copy the URL and key into OBS."
        )
        QMessageBox.information(self, "Help", help_text)

    def open_live_monitor(self) -> None:
        QDesktopServices.openUrl(QUrl("https://livecenter.tiktok.com/live_monitor?lang=en-US"))

    def handle_ui_update(self) -> None:
        self.refresh_account_info(silent=True)

    def closeEvent(self, event: Any) -> None:
        if self._active_session:
            QMessageBox.warning(
                self,
                "Active session",
                "La sesión de Streamlabs sigue activa. Comprueba OBS antes de cerrar.",
            )
        # A pending browser login would otherwise keep a pool thread waiting for
        # up to five minutes and delay process shutdown.
        if self._online_retriever is not None:
            self._online_retriever.cancel()
        self.thread_pool.clear()
        self._clear_sensitive_clipboard()
        event.accept()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("STREAMLABS_KEYGEN_LOG_LEVEL", "WARNING").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    window = StreamApp()
    window.show()
    sys.exit(app.exec())
