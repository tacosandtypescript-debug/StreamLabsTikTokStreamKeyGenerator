import glob
import os
import platform
import re
import shutil
import sys
import json
import threading
import traceback
import hashlib
import tempfile
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QGroupBox, QPushButton, QLineEdit, QLabel, QCheckBox,
                              QListWidget, QMessageBox, QListWidgetItem, QSizePolicy, QFrame,
                              QScrollArea, QToolTip)
from PySide6.QtCore import Signal, QTimer, Qt, QUrl, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QDesktopServices, QIcon, QCursor
from Stream import Stream
from TokenRetriever import TokenRetriever
from BrowserLauncher import open_browser
from Updater import VersionChecker
from SecretStore import protect, unprotect
from packaging import version

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BRAND_LOGO_PATH = os.path.join(APP_DIR, "branding", "fpv-stream-logo.svg")
CONFIG_FILENAME = "config.json"


def _user_config_dir():
    """Per-user fallback for installations where the app folder is read-only."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "FPV Stream")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), "FPV Stream")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "fpv-stream")


def _app_dir_is_writable():
    try:
        with tempfile.NamedTemporaryFile(dir=APP_DIR, prefix=".config-probe-", delete=True):
            return True
    except OSError:
        return False


def default_config_path():
    """Prefer a portable config beside the app, fall back to the user profile."""
    app_config = os.path.join(APP_DIR, CONFIG_FILENAME)
    if _app_dir_is_writable():
        return os.path.abspath(app_config)
    fallback = os.path.join(_user_config_dir(), CONFIG_FILENAME)
    try:
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
        if os.path.exists(app_config) and not os.path.exists(fallback):
            shutil.copy2(app_config, fallback)
    except OSError:
        pass
    return os.path.abspath(fallback)


def instance_key():
    digest = hashlib.sha256(os.path.abspath(default_config_path()).encode()).hexdigest()[:16]
    return "fpv-stream-" + digest


LOCAL_TOKEN_PATTERN = re.compile(rb'"apiToken":"([a-f0-9]+)"', re.IGNORECASE)
LOCAL_TOKEN_CHUNK = 4 * 1024 * 1024


def local_token_files():
    """LevelDB files that may contain the Streamlabs API token."""
    system = platform.system()
    if system == "Windows":
        pattern = os.path.expandvars(r"%appdata%\slobs-client\Local Storage\leveldb\*")
    elif system == "Darwin":
        pattern = os.path.expanduser(
            "~/Library/Application Support/slobs-client/Local Storage/leveldb/*"
        )
    else:
        return []
    files = [path for path in glob.glob(pattern) if path.lower().endswith((".log", ".ldb"))]
    return sorted(files, key=os.path.getmtime, reverse=True)


def token_from_file(path, chunk_size=LOCAL_TOKEN_CHUNK):
    """Read a LevelDB file in chunks without loading the whole file."""
    last = None
    tail = b""
    with open(path, "rb") as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            data = (tail + chunk).replace(b"\x00", b"")
            matches = LOCAL_TOKEN_PATTERN.findall(data)
            if matches:
                last = matches[-1]
            tail = data[-4096:]
    return last.decode("ascii") if last else None


class SingleInstance:
    """One generator per config file; ask the existing window to come forward."""

    def __init__(self, key):
        self.key = key
        self.lock = QLockFile(os.path.join(tempfile.gettempdir(), key + ".lock"))
        self.server = None
        self._activation = None
        self._pending_activation = False

    def acquire(self):
        if not self.lock.tryLock(100):
            return False
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        QLocalServer.removeServer(self.key)
        self.server.listen(self.key)
        self.server.newConnection.connect(self._activate)
        return True

    def on_activation(self, callback):
        self._activation = callback
        if self._pending_activation:
            self._pending_activation = False
            callback()

    def notify_existing(self):
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if not socket.waitForConnected(300):
            return False
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True

    def _activate(self):
        while self.server is not None and self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.waitForReadyRead(200)
            connection.readAll()
            connection.disconnectFromServer()
        if self._activation is not None:
            self._activation()
        else:
            self._pending_activation = True

    def close(self):
        if self.server is not None:
            self.server.close()
            self.server = None
        self.lock.unlock()

BRAND_COLORS = {
    "red": "#DF2531",
    "red_light": "#FF4A54",
    "red_dark": "#A50E1A",
    "background": "#0D0D0F",
    "surface": "#1C1C20",
    "control": "#2B2B2B",
    "border": "#3F3F45",
    "text": "#FFFFFF",
    "muted": "#C5C5CB",
    "disabled": "#83868A",
    "warning": "#F4C95D",
}

class StreamApp(QMainWindow):
    CLIPBOARD_CLEAR_MS = 30000
    update_suggestions = Signal(list)
    update_ui = Signal()
    _token_ready = Signal(object)
    _token_error = Signal(object)
    _restore_local_btn = Signal(int)
    _online_done = Signal(object)
    _login_browser_requested = Signal(object)
    _api_done = Signal(object)
    _search_done = Signal(object)
    _update_ready = Signal(object)

    def __init__(self, *, startup_checks=True, config_path=None):
        super().__init__()
        self.config_path = os.path.abspath(config_path or default_config_path())
        self.stream = None
        self.game_mask_id = ""
        self.live_state = "offline"
        self._api_busy = False
        self._pending_operation = None
        self._client_token = ""
        self._can_go_live = False
        self._saved_session = None
        self._online_retriever = None
        self._pending_token = None
        self._clipboard_text = ""
        self._account_generation = 0
        self._account_cleared = False
        self._account_clear_failed = False
        self._search_generation = 0
        self._search_inflight = False
        self._categories = {}
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._dispatch_search)
        self.init_ui()
        
        if startup_checks:
            QTimer.singleShot(3000, self.check_updates_on_startup)

        # Connect signals
        self.update_suggestions.connect(self.update_suggestions_list)
        self.update_ui.connect(self.handle_ui_update)
        self._token_ready.connect(self._apply_local_token)
        self._token_error.connect(self._show_local_token_error)
        self._restore_local_btn.connect(self._do_restore_local_btn)
        self._online_done.connect(self._finish_online_token)
        self._login_browser_requested.connect(self._open_login_browser)
        self._api_done.connect(self._finish_api)
        self._search_done.connect(self._finish_search)
        self._update_ready.connect(self._show_update)
        self.load_config()
        self._sync_controls()

    def init_ui(self):
        self.setWindowTitle("FPV Stream · Generador de clave de TikTok")
        self.setMinimumSize(800, 600)
        self._brand_icon = QIcon(BRAND_LOGO_PATH)
        self.setWindowIcon(self._brand_icon)
        self._apply_brand_theme()

        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)
        main_widget.setLayout(main_layout)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(main_widget)
        self.setCentralWidget(self.scroll_area)

        brand_header = QWidget()
        brand_header_layout = QHBoxLayout(brand_header)
        brand_header_layout.setContentsMargins(4, 0, 4, 0)
        brand_header_layout.setSpacing(10)

        self.brand_logo = QLabel()
        self.brand_logo.setFixedSize(48, 48)
        self.brand_logo.setPixmap(self._brand_icon.pixmap(48, 48))
        self.brand_logo.setScaledContents(True)
        self.brand_logo.setAccessibleName("Logotipo de FPV Stream")
        brand_header_layout.addWidget(self.brand_logo)

        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(0)
        self.brand_name = QLabel("FPV Stream")
        self.brand_name.setObjectName("brandTitle")
        self.brand_name.setAccessibleName("FPV Stream")
        brand_copy.addWidget(self.brand_name)
        brand_subtitle = QLabel("Preparación de transmisiones de TikTok")
        brand_subtitle.setObjectName("brandSubtitle")
        brand_copy.addWidget(brand_subtitle)
        brand_header_layout.addLayout(brand_copy)
        brand_header_layout.addStretch()
        main_layout.addWidget(brand_header)

        brand_rule = QFrame()
        brand_rule.setFrameShape(QFrame.HLine)
        brand_rule.setFrameShadow(QFrame.Plain)
        brand_rule.setFixedHeight(2)
        brand_rule.setStyleSheet(f"background-color: {BRAND_COLORS['red']}; border: none;")
        main_layout.addWidget(brand_rule)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        main_layout.addLayout(content_layout)

        # Left column
        left_column = QVBoxLayout()
        left_column.setSpacing(8)
        content_layout.addLayout(left_column)

        # Token Section
        token_group = QGroupBox("Carga de token")
        token_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        left_column.addWidget(token_group)

        token_layout = QVBoxLayout()
        token_layout.setContentsMargins(8, 12, 8, 8)
        token_layout.setSpacing(6)
        token_group.setLayout(token_layout)

        # Token Entry Row
        token_entry_row = QHBoxLayout()
        token_entry_row.setSpacing(5)

        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Pega el token o cárgalo abajo…")
        self.token_entry.setEchoMode(QLineEdit.Password)
        self.token_entry.setFixedHeight(28)
        self.token_entry.textChanged.connect(self.handle_token_change)
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_entry_row.addWidget(self.token_entry)

        # Token visibility control
        self.toggle_token_btn = QPushButton("Ver")
        self.toggle_token_btn.setFixedSize(60, 28)
        self.toggle_token_btn.setToolTip("Mostrar token")
        self.toggle_token_btn.setAccessibleName("Mostrar token")
        self.toggle_token_btn.clicked.connect(self.toggle_token_visibility)
        token_entry_row.addWidget(self.toggle_token_btn)

        token_layout.addLayout(token_entry_row)

        # Token Load Buttons Row
        load_buttons_row = QHBoxLayout()
        load_buttons_row.setSpacing(5)

        # Local Token Button
        self.load_local_btn = QPushButton("Cargar desde el PC")
        self.load_local_btn.setFixedHeight(30)
        self.load_local_btn.setToolTip("Cargar el token desde los datos de Streamlabs para escritorio")
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons_row.addWidget(self.load_local_btn)

        # Online Token Button
        self.load_online_btn = QPushButton("Cargar desde la web")
        self.load_online_btn.setFixedHeight(30)
        self.load_online_btn.setToolTip("Obtener el token iniciando sesión en el navegador")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons_row.addWidget(self.load_online_btn)
        self.cancel_login_btn = QPushButton("Cancelar")
        self.cancel_login_btn.setFixedHeight(30)
        self.cancel_login_btn.setEnabled(False)
        self.cancel_login_btn.clicked.connect(self.cancel_online_login)
        load_buttons_row.addWidget(self.cancel_login_btn)

        token_layout.addLayout(load_buttons_row)
        self.change_account_btn = QPushButton("Cambiar cuenta")
        self.change_account_btn.setFixedHeight(30)
        self.change_account_btn.setToolTip("Borrar la cuenta guardada en este generador e iniciar sesión con otra")
        self.change_account_btn.clicked.connect(self.change_account)
        token_layout.addWidget(self.change_account_btn)
        self.login_status = QLabel("")
        self.login_status.setWordWrap(True)
        self.login_status.setTextFormat(Qt.PlainText)
        self.login_status.setMinimumHeight(36)
        token_layout.addWidget(self.login_status)

        # Binary Location Input Row
        if platform.system() == "Linux":
            binary_row = QHBoxLayout()
            binary_row.setSpacing(5)

            self.binary_location_entry = QLineEdit()
            self.binary_location_entry.setPlaceholderText("Ruta personalizada de Chrome (opcional)")
            self.binary_location_entry.setFixedHeight(28)
            self.binary_location_entry.setToolTip("Déjala vacía para detectar Chrome automáticamente en Linux")
            binary_row.addWidget(self.binary_location_entry)
            
            token_layout.addLayout(binary_row)


        # Account Info Section
        account_info_label = QLabel("Información de la cuenta")
        account_info_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        token_layout.addWidget(account_info_label)

        # Username
        field_label_width = max(
            self.fontMetrics().horizontalAdvance(text)
            for text in ("Nombre de usuario:", "Estado:", "Puede emitir:")
        ) + 8
        username_row = QHBoxLayout()
        username_row.setSpacing(5)
        username_label = QLabel("Nombre de usuario:")
        username_label.setFixedWidth(field_label_width)
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setFixedHeight(26)
        username_row.addWidget(username_label)
        username_row.addWidget(self.tiktok_username)
        token_layout.addLayout(username_row)

        # Status
        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        status_label = QLabel("Estado:")
        status_label.setFixedWidth(field_label_width)
        self.app_status = QLineEdit()
        self.app_status.setReadOnly(True)
        self.app_status.setToolTip("Estado del acceso de la cuenta en Streamlabs; no indica recepción de vídeo.")
        self.app_status.setFixedHeight(26)
        status_row.addWidget(status_label)
        status_row.addWidget(self.app_status)
        token_layout.addLayout(status_row)

        # Go Live Status
        live_row = QHBoxLayout()
        live_row.setSpacing(5)
        live_label = QLabel("Puede emitir:")
        live_label.setFixedWidth(field_label_width)
        self.can_go_live = QLineEdit()
        self.can_go_live.setReadOnly(True)
        self.can_go_live.setToolTip("Permiso para preparar una sesión; no confirma que TikTok reciba vídeo.")
        self.can_go_live.setFixedHeight(26)
        live_row.addWidget(live_label)
        live_row.addWidget(self.can_go_live)
        token_layout.addLayout(live_row)
        
        # Refresh account info button
        refresh_btn = self.refresh_btn = QPushButton("Actualizar información de la cuenta")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setToolTip("Actualizar la información de la cuenta")
        refresh_btn.clicked.connect(self.refresh_account_info)
        token_layout.addWidget(refresh_btn)

        # Add stretch to prevent expansion
        token_layout.addStretch()

        # Stream Details
        stream_group = QGroupBox("Detalles de la transmisión")
        left_column.addWidget(stream_group)
        stream_layout = QVBoxLayout()
        stream_layout.setContentsMargins(8, 8, 8, 8)  # Left, Top, Right, Bottom margins
        stream_layout.setSpacing(5)  # Reduced spacing between widgets
        stream_group.setLayout(stream_layout)

        # Stream Title
        title_label = QLabel("Título de la transmisión:")
        title_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(title_label)
        self.stream_title = QLineEdit()
        self.stream_title.setFixedHeight(28)  # Slightly smaller height
        stream_layout.addWidget(self.stream_title)

        # Game Category
        game_label = QLabel("Categoría del juego:")
        game_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(game_label)
        self.game_category = QLineEdit()
        self.game_category.setClearButtonEnabled(True)
        self.game_category.setFixedHeight(28)
        self.game_category.textChanged.connect(self.handle_game_search)
        stream_layout.addWidget(self.game_category)

        # Suggestions List
        self.suggestions_list = QListWidget()
        self.suggestions_list.hide()
        self.suggestions_list.setFixedHeight(100)  # Limit height of suggestions
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        stream_layout.addWidget(self.suggestions_list)

        # Mature Checkbox
        self.mature_checkbox = QCheckBox("Activar contenido para adultos")
        self.mature_checkbox.setStyleSheet("padding: 2px;")  # Reduce internal padding
        stream_layout.addWidget(self.mature_checkbox)

        # Add stretch to push everything up
        stream_layout.addStretch()

        # Right column (Controls)
        control_group = QGroupBox("Control de transmisión")
        control_group.setMinimumWidth(250)  # Set a minimum width for the control column
        content_layout.addWidget(control_group)

        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(8, 12, 8, 8)  # Tighter margins
        control_layout.setSpacing(6)  # Reduced spacing between widgets
        control_group.setLayout(control_layout)

        # Buttons row
        button_row = QHBoxLayout()
        button_row.setSpacing(5)  # Tight spacing between buttons

        self.go_live_btn = QPushButton("Preparar transmisión")
        self.go_live_btn.setObjectName("primaryAction")
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.clicked.connect(self.start_stream)
        self.go_live_btn.setFixedHeight(32)  # Consistent button height
        button_row.addWidget(self.go_live_btn)

        self.end_live_btn = QPushButton("Finalizar transmisión")
        self.end_live_btn.setObjectName("dangerAction")
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.clicked.connect(self.end_stream)
        self.end_live_btn.setFixedHeight(32)
        button_row.addWidget(self.end_live_btn)

        control_layout.addLayout(button_row)

        self.live_status = QLabel("Sin sesión preparada en este generador")
        self.live_status.setStyleSheet(f"color: {BRAND_COLORS['muted']}; font-weight: bold;")
        self.live_status.setWordWrap(True)
        self.live_status.setMinimumHeight(48)
        self.live_status.setTextFormat(Qt.PlainText)
        self.live_status.setAccessibleName("Estado de la sesión de TikTok")
        control_layout.addWidget(self.live_status)
        self.video_status = QLabel("Señal de vídeo en TikTok: sin confirmar. Compruébala en Live Monitor.")
        self.video_status.setWordWrap(True)
        self.video_status.setMinimumHeight(36)
        control_layout.addWidget(self.video_status)
        self.resolve_session_btn = QPushButton("Confirmar cierre manual…")
        self.resolve_session_btn.setVisible(False)
        self.resolve_session_btn.setFixedHeight(28)
        policy = self.resolve_session_btn.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.resolve_session_btn.setSizePolicy(policy)
        self.resolve_session_btn.clicked.connect(self.confirm_manual_close)
        control_layout.addWidget(self.resolve_session_btn)

        # URL Section
        url_label = QLabel("URL de transmisión:")
        url_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(url_label)

        self.stream_url = QLineEdit()
        self.stream_url.setReadOnly(True)
        self.stream_url.setFixedHeight(28)  # Compact height
        control_layout.addWidget(self.stream_url)

        self.copy_url_btn = QPushButton("Copiar URL")
        self.copy_url_btn.setFixedHeight(28)
        self.copy_url_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_url))
        control_layout.addWidget(self.copy_url_btn)

        # Key Section
        key_label = QLabel("Clave de transmisión:")
        key_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(key_label)

        self.stream_key = QLineEdit()
        self.stream_key.setReadOnly(True)
        self.stream_key.setEchoMode(QLineEdit.Password)
        self.stream_key.setFixedHeight(28)
        control_layout.addWidget(self.stream_key)

        self.copy_key_btn = QPushButton("Copiar clave")
        self.copy_key_btn.setFixedHeight(28)
        self.copy_key_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_key))
        control_layout.addWidget(self.copy_key_btn)
        self.show_key_btn = QPushButton("Mostrar clave")
        self.show_key_btn.setFixedHeight(28)
        self.show_key_btn.clicked.connect(self.toggle_key_visibility)
        control_layout.addWidget(self.show_key_btn)

        # Add stretch to prevent expansion of widgets
        control_layout.addStretch()
        # Bottom buttons
        bottom_buttons = QHBoxLayout()
        left_column.addLayout(bottom_buttons)

        self.save_btn = QPushButton("Guardar configuración")
        self.save_btn.clicked.connect(lambda: self.save_config())
        bottom_buttons.addWidget(self.save_btn)

        self.help_btn = QPushButton("Ayuda")
        self.help_btn.clicked.connect(self.show_help)
        bottom_buttons.addWidget(self.help_btn)

        self.monitor_btn = QPushButton("Abrir Live Monitor")
        self.monitor_btn.clicked.connect(self.open_live_monitor)
        bottom_buttons.addWidget(self.monitor_btn)

    def _apply_brand_theme(self):
        colors = BRAND_COLORS
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {colors['background']};
                color: {colors['text']};
            }}
            QGroupBox {{
                border: 1px solid {colors['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {colors['red_light']};
            }}
            QLabel#brandTitle {{
                color: {colors['text']};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#brandSubtitle {{
                color: {colors['muted']};
                font-size: 11px;
            }}
            QLineEdit, QListWidget {{
                background-color: {colors['surface']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 5px;
                selection-background-color: {colors['red']};
                selection-color: {colors['text']};
            }}
            QLineEdit:focus {{
                border: 1px solid {colors['red_light']};
            }}
            QLineEdit:read-only {{
                color: {colors['muted']};
            }}
            QListWidget::item:selected {{
                background-color: {colors['red']};
                color: {colors['text']};
            }}
            QPushButton {{
                background-color: {colors['control']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 5px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: #3F3F45;
                border-color: {colors['red_light']};
            }}
            QPushButton:pressed {{
                background-color: {colors['red_dark']};
            }}
            QPushButton:disabled {{
                background-color: #23232A;
                color: {colors['disabled']};
                border-color: #34343A;
            }}
            QPushButton#primaryAction {{
                background-color: {colors['red']};
                border-color: {colors['red']};
                font-weight: 700;
            }}
            QPushButton#primaryAction:hover {{
                background-color: {colors['red_light']};
                border-color: {colors['red_light']};
            }}
            QPushButton#primaryAction:disabled {{
                background-color: #23232A;
                color: {colors['disabled']};
                border-color: #34343A;
            }}
            QPushButton#dangerAction {{
                border-color: {colors['red']};
                color: {colors['red_light']};
            }}
            QPushButton#dangerAction:disabled {{
                background-color: #23232A;
                color: {colors['disabled']};
                border-color: #34343A;
            }}
            QCheckBox {{
                color: {colors['text']};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {colors['muted']};
                border-radius: 3px;
                background-color: {colors['surface']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {colors['red']};
                border-color: {colors['red']};
            }}
            QToolTip {{
                background-color: {colors['surface']};
                color: {colors['text']};
                border: 1px solid {colors['red']};
            }}
        """)

    def toggle_token_visibility(self):
        """Alterna la visibilidad del token."""
        if self.token_entry.echoMode() == QLineEdit.Normal:
            self.token_entry.setEchoMode(QLineEdit.Password)
            self.toggle_token_btn.setText("Ver")
            self.toggle_token_btn.setToolTip("Mostrar token")
            self.toggle_token_btn.setAccessibleName("Mostrar token")
        else:
            self.token_entry.setEchoMode(QLineEdit.Normal)
            self.toggle_token_btn.setText("Ocultar")
            self.toggle_token_btn.setToolTip("Ocultar token")
            self.toggle_token_btn.setAccessibleName("Ocultar token")

    def handle_token_change(self):
        self._sync_controls()

    def _set_live_state(self, state, detail=""):
        self.live_state = state
        labels = {
            "starting": ("Creando sesión de TikTok…", f"color: {BRAND_COLORS['warning']}; font-weight: bold;"),
            "prepared": ("Sesión de TikTok preparada", f"color: {BRAND_COLORS['warning']}; font-weight: bold;"),
            "uncertain": ("Estado de la sesión sin confirmar", f"color: {BRAND_COLORS['warning']}; font-weight: bold;"),
            "ending": ("Solicitando cierre de la sesión…", f"color: {BRAND_COLORS['warning']}; font-weight: bold;"),
            "offline": ("Sin sesión preparada en este generador", f"color: {BRAND_COLORS['muted']}; font-weight: bold;"),
            "error": ("Error de sesión", f"color: {BRAND_COLORS['red_light']}; font-weight: bold;"),
        }
        text, style = labels.get(state, labels["error"])
        self.live_status.setText(f"{text}{(' — ' + detail) if detail else ''}")
        self.live_status.setStyleSheet(style)
        self._sync_controls()

    def load_config(self):
        data = self._read_config()
        if data is None:
            self._quarantine_config()
            data = {}
        self._saved_session = data.get("session") if isinstance(data.get("session"), dict) else None
        raw_token = self._config_text(data.get("token"))
        token = unprotect(raw_token)
        if raw_token and not token:
            self.live_status.setText(
                "No se pudo descifrar el token guardado en este equipo. Vuelve a cargar la cuenta."
            )
        self.token_entry.setText(token)
        self.stream_title.setText(self._config_text(data.get("title")))
        self.game_category.setText(self._config_text(data.get("game")))
        audience = data.get("audience_type", "0")
        self.mature_checkbox.setChecked(str(audience).lower() in ("1", "true"))

        self.refresh_account_info()

    @staticmethod
    def _config_text(value):
        return value if isinstance(value, str) else ""

    def _read_config(self):
        """Return a validated config dict, or None when the file is corrupt."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        text_fields = ("token", "title", "game", "audience_type")
        if any(key in data and not isinstance(data[key], str) for key in text_fields):
            return None
        if "session" in data and not isinstance(data["session"], dict):
            return None
        return data

    def _quarantine_config(self):
        """Keep a copy of an unreadable config so startup can continue."""
        backup = self.config_path + ".bak"
        try:
            os.replace(self.config_path, backup)
        except OSError:
            return False
        self.live_status.setText(
            "La configuración guardada estaba dañada. Se conservó una copia en config.json.bak."
        )
        return True

    def save_config(self, show_message=True, data=None):
        if data is None:
            data = {
                "title": self.stream_title.text(),
                "game": self.game_category.text(),
                "audience_type": "1" if self.mature_checkbox.isChecked() else "0",
                "token": self.token_entry.text()
            }
            if self.stream and (self.stream.id or self.stream.session_uncertain or
                                self._api_busy and self._pending_operation in ("start", "end")):
                data["session"] = {"id": self.stream.id, "uncertain": self.stream.session_uncertain or self._api_busy,
                                   "account": hashlib.sha256(self._client_token.encode()).hexdigest()}
        try:
            data["token"] = protect(data.get("token", ""))
        except OSError:
            self.live_status.setText("No se pudo cifrar el token para guardarlo. Comprueba el sistema.")
            return False
        temporary = None
        try:
            directory = os.path.dirname(self.config_path)
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix=".config-", suffix=".json", delete=False) as file:
                temporary = file.name
                json.dump(data, file)
            os.replace(temporary, self.config_path)
        except OSError:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            self.live_status.setText("No se pudo guardar el estado local. Comprueba los permisos de la carpeta.")
            return False
        if show_message:
            QMessageBox.information(self, "Configuración guardada", "La configuración se ha guardado correctamente.")
        return True

    def _sync_controls(self):
        known = bool(self.stream and self.stream.id)
        uncertain = bool(self.stream and self.stream.session_uncertain)
        login_pending = self._online_retriever is not None
        locked = self._api_busy or known or uncertain or login_pending or self._account_clear_failed
        current_account = bool(self.stream and self._client_token == self.token_entry.text().strip())
        self.go_live_btn.setEnabled(current_account and self._can_go_live and not locked)
        self.end_live_btn.setEnabled(known and not self._api_busy)
        self.token_entry.setEnabled(not locked)
        self.load_local_btn.setEnabled(not locked)
        self.load_online_btn.setEnabled(not locked)
        self.cancel_login_btn.setEnabled(login_pending)
        self.change_account_btn.setEnabled(
            bool(self.token_entry.text().strip() or self.stream or self._account_clear_failed) and not login_pending
            and (not self._api_busy or self._pending_operation == "info")
        )
        self.load_online_btn.setText("Esperando sesión…" if login_pending else "Cargar desde la web")
        if known or uncertain:
            self.load_online_btn.setToolTip(
                "Cierra la sesión actual o confirma su cierre en Live Monitor antes de cambiar de cuenta."
            )
        else:
            self.load_online_btn.setToolTip("Abre el navegador para iniciar sesión con otra cuenta")
        self.refresh_btn.setEnabled(not self._api_busy and not login_pending and bool(self.token_entry.text().strip()))
        for control in (self.stream_title, self.game_category, self.mature_checkbox):
            control.setEnabled(not locked)
        usable = known and self.live_state == "prepared" and not self._api_busy
        self.copy_url_btn.setEnabled(usable and bool(self.stream_url.text()))
        self.copy_key_btn.setEnabled(usable and bool(self.stream_key.text()))
        self.show_key_btn.setEnabled(usable and bool(self.stream_key.text()))
        self.resolve_session_btn.setVisible(uncertain and not self._api_busy)
        self.save_btn.setEnabled(not self._api_busy)

    def _run_api(self, operation, action):
        if self._api_busy or not self.stream:
            return False
        self._search_timer.stop()
        self._search_generation += 1
        self._api_busy = True
        self._pending_operation = operation
        client = self.stream
        self._sync_controls()
        if operation in ("start", "end") and self.save_config(False) is False:
            self._api_busy = False
            self._pending_operation = None
            self._set_live_state("error", "No se pudo guardar el estado. La solicitud no se envió.")
            return False
        def work():
            try:
                with client._lock:
                    result = action()
                    error = client.last_error
            except Exception:
                # Never expose arbitrary exception strings containing secrets.
                result, error = None, "La solicitud falló; el resultado no está confirmado."
                if operation in ("start", "end"):
                    client.session_uncertain = True
            try:
                self._api_done.emit((client, operation, result, error))
            except RuntimeError:
                pass  # Window already destroyed; no worker may mutate widgets.
        threading.Thread(target=work, daemon=True, name="streamlabs-" + operation).start()
        return True

    def _clear_credentials(self):
        self.stream_url.clear()
        self.stream_key.clear()
        self.stream_key.setEchoMode(QLineEdit.Password)
        self.show_key_btn.setText("Mostrar clave")

    def change_account(self):
        if self.stream and (self.stream.id or self.stream.session_uncertain):
            self.login_status.setText(
                "Finaliza la transmisión actual o confirma su cierre en Live Monitor antes de cambiar de cuenta."
            )
            return
        if self._api_busy and self._pending_operation != "info":
            self.login_status.setText("Espera a que termine la solicitud antes de cambiar de cuenta.")
            return

        self.cancel_online_login()
        cleared = {
            "title": self.stream_title.text(),
            "game": self.game_category.text(),
            "audience_type": "1" if self.mature_checkbox.isChecked() else "0",
            "token": "",
        }
        # Persist the empty identity before clearing the widgets, so a failed
        # write leaves the previous in-memory account usable.
        if self.save_config(False, data=cleared) is False:
            self._account_clear_failed = True
            self.login_status.setText(
                "No se pudo borrar la cuenta guardada. Comprueba los permisos de la carpeta y vuelve a intentar."
            )
            self._sync_controls()
            return
        self._account_clear_failed = False

        self._account_generation += 1
        self._search_timer.stop()
        self._search_generation += 1
        self._search_inflight = False
        self._categories.clear()
        self.game_mask_id = ""
        self.suggestions_list.clear()
        self.suggestions_list.hide()
        self.stream = None
        self._client_token = ""
        self._saved_session = None
        self._can_go_live = False
        self._api_busy = False
        self._pending_operation = None
        self._pending_token = None
        self.token_entry.clear()
        self.token_entry.setEchoMode(QLineEdit.Password)
        self.toggle_token_btn.setText("Ver")
        self.toggle_token_btn.setToolTip("Mostrar token")
        self.toggle_token_btn.setAccessibleName("Mostrar token")
        self.tiktok_username.clear()
        self.app_status.clear()
        self.can_go_live.clear()
        self._clear_credentials()
        self.load_local_btn.setText("Cargar desde el PC")
        self._account_cleared = True
        self._set_live_state("offline", "No hay ninguna cuenta cargada.")
        self.fetch_online_token()

    def _finish_api(self, outcome):
        client, operation, result, error = outcome
        if client is not self.stream:
            return
        self._api_busy = False
        self._pending_operation = None
        if operation == "info":
            self._can_go_live = bool(result and result.get("can_be_live") is True and not error)
            if error:
                self.app_status.setText(error)
                self.can_go_live.setText("Sin confirmar")
                self._set_live_state("uncertain" if client.id or client.session_uncertain else "error", error)
            else:
                user, application = result.get("user"), result.get("application_status")
                self.tiktok_username.setText(str(user.get("username", "Desconocido")) if isinstance(user, dict) else "Desconocido")
                self.app_status.setText(str(application.get("status", "Desconocido")) if isinstance(application, dict) else "Desconocido")
                self.can_go_live.setText("Sí" if self._can_go_live else "No")
                if not client.id and not client.session_uncertain:
                    self._set_live_state("offline")
                    self.fetch_game_mask_id(self.game_category.text())
        elif operation == "start":
            if result and result[0] and result[1] and not error:
                self.stream_url.setText(result[0])
                self.stream_key.setText(result[1])
                self.stream_key.setEchoMode(QLineEdit.Password)
                self._set_live_state("prepared")
            else:
                self._set_live_state("uncertain" if client.id or client.session_uncertain else "error", error)
        elif operation == "end":
            if result is True and not error:
                self._clear_credentials()
                self._set_live_state("offline", "Streamlabs confirmó el cierre.")
            else:
                self._set_live_state("uncertain", error or "No se confirmó el cierre. Revisa Live Monitor o vuelve a intentar finalizar la transmisión.")
        self.save_config(False)
        self._sync_controls()
        if self._pending_token and not self._api_busy:
            token, message = self._pending_token
            self._pending_token = None
            self._apply_token(token, success_message=message)

    def load_account_info(self):
        if self.stream and not self._api_busy:
            self.app_status.setText("Consultando Streamlabs…")
            self._run_api("info", self.stream.getInfo)

    def refresh_account_info(self):
        if self._api_busy:
            return
        token = self.token_entry.text().strip()
        if self.stream and (self.stream.id or self.stream.session_uncertain) and token != self._client_token:
            self.token_entry.blockSignals(True)
            self.token_entry.setText(self._client_token)
            self.token_entry.blockSignals(False)
            self._set_live_state("uncertain", "Cierra la sesión anterior en Live Monitor antes de cambiar de cuenta.")
            return
        if token and (self.stream is None or token != self._client_token):
            self.stream = Stream(token)
            self._client_token = token
            self._can_go_live = False
            self._clear_credentials()
            self.tiktok_username.clear()
            self.app_status.clear()
            self.can_go_live.clear()
            restored = self._saved_session
            self._saved_session = None
            if isinstance(restored, dict) and restored.get("account") == hashlib.sha256(token.encode()).hexdigest():
                self.stream.id = restored.get("id")
                self.stream.session_uncertain = bool(self.stream.id or restored.get("uncertain"))
                if self.stream.session_uncertain:
                    self._set_live_state("uncertain", "Sesión recuperada del generador. Comprueba su estado en Live Monitor.")
        if token:
            self.load_account_info()
        self.save_config(False)

    def _do_restore_local_btn(self, generation):
        if generation != self._account_generation:
            return
        self.load_local_btn.setText("Cargar desde el PC")
        self._sync_controls()

    def _apply_local_token(self, outcome):
        generation, token = outcome
        if generation == self._account_generation and self._online_retriever is None:
            self._apply_token(token)

    def _show_local_token_error(self, outcome):
        generation, message = outcome
        if generation == self._account_generation:
            QMessageBox.critical(self, "Error", message)

    def load_local_token(self):
        if platform.system() not in ("Windows", "Darwin"):
            QMessageBox.critical(
                self, "Error", "Este sistema operativo no permite recuperar el token local."
            )
            return
        self._account_generation += 1
        generation = self._account_generation
        self.load_local_btn.setEnabled(False)
        self.load_local_btn.setText("Buscando…")

        def _run():
            try:
                token = self._find_local_token()
            except Exception as e:
                print(traceback.format_exc())
                self._token_error.emit((generation, "No se pudo buscar el token local. Vuelve a intentar."))
                return
            finally:
                self._restore_local_btn.emit(generation)

            if token:
                self._token_ready.emit((generation, token))
            else:
                self._token_error.emit((generation,
                    "No se encontró ningún token de API local. Asegúrate de que Streamlabs está instalado "
                    "y has iniciado sesión con TikTok."
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _find_local_token(self) -> str | None:
        """Blocking file scan — runs on a worker thread."""
        for file in local_token_files():
            try:
                token = token_from_file(file)
            except OSError as error:
                print(f"Error reading {file}: {error}")
                continue
            if token:
                return token
        return None

    def fetch_online_token(self):
        if self._account_clear_failed:
            self.login_status.setText("Pulsa Cambiar cuenta para volver a intentar borrar la cuenta guardada antes de iniciar sesión.")
            return
        if self._online_retriever or self._api_busy or self.stream and (self.stream.id or self.stream.session_uncertain):
            return
        retriever = TokenRetriever()
        self._account_generation += 1
        self._online_retriever = retriever
        self.load_local_btn.setText("Cargar desde el PC")
        self.login_status.setText(
            "Cuenta anterior eliminada de este generador. En TikTok pulsa «Cambiar de cuenta» y elige la nueva."
            if self._account_cleared else
            "Abriendo el inicio de sesión de TikTok. Puedes pulsar Cancelar para reintentar."
        )
        self._sync_controls()

        def launch_login_page(url):
            if retriever.cancelled.is_set():
                return False
            if open_browser(url):
                return True

            request = {
                "retriever": retriever,
                "url": url,
                "opened": False,
                "completed": threading.Event(),
            }
            self._login_browser_requested.emit(request)
            # The signal is handled by Qt's GUI thread. Do not let the worker
            # wait forever if the window is closing or the event loop stops.
            if not request["completed"].wait(timeout=5):
                return False
            return request["opened"]

        def _run():
            token = None
            try:
                token = retriever.retrieve_token(browser_opener=launch_login_page)
            except Exception:
                retriever.last_error = "No se pudo iniciar la sesión web. Puedes reintentar."
            finally:
                try:
                    self._online_done.emit((retriever, token))
                except RuntimeError:
                    pass

        threading.Thread(target=_run, daemon=True, name="streamlabs-web-login").start()

    def _open_login_browser(self, request):
        """Open OAuth in the native browser launcher on the GUI thread."""
        retriever = request.get("retriever")
        opened = False
        if retriever is self._online_retriever and not retriever.cancelled.is_set():
            try:
                opened = bool(QDesktopServices.openUrl(QUrl(request["url"])))
            except Exception:
                opened = False
        request["opened"] = opened
        request["completed"].set()

    def cancel_online_login(self):
        retriever = self._online_retriever
        if retriever is None:
            return
        retriever.cancel()
        self._online_retriever = None
        self.login_status.setText(
            "Inicio cancelado. No hay ninguna cuenta cargada. Pulsa Cargar desde la web para reintentar."
            if self._account_cleared else "Inicio de sesión cancelado. Puedes reintentar."
        )
        self._sync_controls()

    def _finish_online_token(self, outcome):
        retriever, token = outcome
        # A cancelled attempt must never overwrite a later login's account.
        if retriever is not self._online_retriever:
            return
        self._online_retriever = None
        self._sync_controls()
        if token and not retriever.cancelled.is_set():
            self._apply_token(token, success_message="Inicio de sesión completado.")
        else:
            message = retriever.last_error or "No se completó el inicio de sesión. Puedes reintentar."
            self.login_status.setText(message + (" No hay ninguna cuenta cargada." if self._account_cleared else ""))

    def _apply_token(self, token: str, success_message: str = ""):
        """Apply a freshly retrieved token — always called on the GUI thread."""
        if self._api_busy:
            self._pending_token = (token, success_message)
            prefix = success_message + " " if success_message else ""
            self.login_status.setText(prefix + "Se aplicará al terminar la solicitud en curso.")
            return
        if self.stream and (self.stream.id or self.stream.session_uncertain):
            self.login_status.setText(
                "Hay una sesión abierta; finalízala antes de aplicar la nueva cuenta."
            )
            return
        if success_message:
            self.login_status.setText(success_message)
        self.token_entry.setText(token)
        self._account_cleared = False
        self.refresh_account_info()

    def fetch_game_mask_id(self, game_name):
        self.game_mask_id = self._categories.get(game_name, "")
        if game_name and game_name not in self._categories:
            self.handle_game_search(game_name)

    def handle_game_search(self, text):
        self._search_generation += 1
        self._search_timer.stop()
        self.game_mask_id = self._categories.get(text, "")
        if text and self.stream:
            self._search_timer.start()
        else:
            self.suggestions_list.clear()
            self.suggestions_list.hide()

    def _dispatch_search(self):
        query = self.game_category.text().strip()
        client = self.stream
        if not query or client is None or self._search_inflight or self._api_busy or client.id or client.session_uncertain:
            return
        generation = self._search_generation
        self._search_inflight = True
        def work():
            try:
                with client._lock:
                    categories = client.search(query)
                    error = client.last_error
            except Exception:
                categories, error = [], "No se pudieron consultar las categorías."
            try:
                self._search_done.emit((client, generation, query, categories, error))
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="streamlabs-search").start()

    def _finish_search(self, outcome):
        client, generation, query, categories, error = outcome
        self._search_inflight = False
        if client is not self.stream:
            return
        if generation != self._search_generation or query != self.game_category.text().strip():
            if self.game_category.text().strip():
                self._search_timer.start()
            return
        if self._api_busy or client.id or client.session_uncertain:
            return
        self._categories = {item["full_name"]: item["game_mask_id"] for item in categories}
        self.game_mask_id = self._categories.get(query, "")
        self.update_suggestions_list(categories)
        if error:
            self.app_status.setText(error)

    def update_suggestions_list(self, categories):
        self.suggestions_list.clear()
        for category in categories:
            self.suggestions_list.addItem(QListWidgetItem(category['full_name']))
        self.suggestions_list.setVisible(bool(categories))

    def handle_suggestion_selected(self, item):
        self._search_generation += 1
        self._search_timer.stop()
        self.game_category.blockSignals(True)
        self.game_category.setText(item.text())
        self.game_category.blockSignals(False)
        self.game_mask_id = self._categories.get(item.text(), "")
        self.suggestions_list.hide()

    def start_stream(self):
        if self._api_busy or not self.stream or self.stream.id or self.stream.session_uncertain:
            return
        if not self._can_go_live or self.token_entry.text().strip() != self._client_token:
            self._set_live_state("error", "Actualiza la cuenta y comprueba el acceso LIVE antes de iniciar.")
            return
        if not self.stream_title.text().strip():
            self._set_live_state("error", "Escribe un título antes de preparar la sesión.")
            self.stream_title.setFocus()
            return
        category = self.game_category.text().strip()
        if category and category != "Other" and category not in self._categories:
            self._set_live_state("error", "Elige una categoría de las sugerencias o usa Other.")
            self.game_category.setFocus()
            return
        self._clear_credentials()
        self._set_live_state("starting")
        client = self.stream
        title, category = self.stream_title.text(), self.game_mask_id
        audience = "1" if self.mature_checkbox.isChecked() else "0"
        self._run_api("start", lambda: client.start(title, category, audience))

    def end_stream(self):
        if self._api_busy or not self.stream or not self.stream.id:
            return
        self._set_live_state("ending")
        self._run_api("end", self.stream.end)

    def toggle_key_visibility(self):
        visible = self.stream_key.echoMode() == QLineEdit.Normal
        self.stream_key.setEchoMode(QLineEdit.Password if visible else QLineEdit.Normal)
        self.show_key_btn.setText("Mostrar clave" if visible else "Ocultar clave")

    def confirm_manual_close(self):
        if self._api_busy or not self.stream or not self.stream.session_uncertain:
            return
        answer = QMessageBox.question(self, "Confirmar cierre manual",
            "Comprueba en Live Monitor que la sesión ya terminó. Esta acción solo borra el estado local; "
            "no detiene una sesión que siga activa en TikTok. ¿Has confirmado que terminó?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        self.stream.id = None
        self.stream.session_uncertain = False
        self._clear_credentials()
        self._set_live_state("offline", "Cierre confirmado manualmente en Live Monitor.")
        self.save_config(False)

    def closeEvent(self, event):
        if self._api_busy:
            self.live_status.setText("Espera a que termine la solicitud antes de cerrar el generador.")
            event.ignore()
            return
        if self.stream and (self.stream.id or self.stream.session_uncertain):
            answer = QMessageBox.question(self, "Sesión pendiente",
                "Cerrar el generador no termina la sesión de TikTok. Su estado se conservará para volver a revisarlo. "
                "¿Cerrar el generador?", QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Close:
                event.ignore()
                return
        self.save_config(False)
        self.cancel_online_login()
        self._clear_clipboard_if_unchanged(self._clipboard_text)
        event.accept()

    def copy_to_clipboard(self, widget):
        text = widget.text()
        QApplication.clipboard().setText(text)
        self._clipboard_text = text
        QTimer.singleShot(
            self.CLIPBOARD_CLEAR_MS,
            lambda: self._clear_clipboard_if_unchanged(text),
        )
        QToolTip.showText(QCursor.pos(), "Copiado al portapapeles", self)

    def _clear_clipboard_if_unchanged(self, text):
        if not text:
            return
        clipboard = QApplication.clipboard()
        if clipboard.text() == text:
            clipboard.clear()
        if self._clipboard_text == text:
            self._clipboard_text = ""

    def show_help(self):
        help_text = """1. Solicita acceso LIVE en Streamlabs
2. Instala Streamlabs e inicia sesión con TikTok
3. Usa esta aplicación para obtener el token de Streamlabs
4. Prepara la transmisión"""
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Ayuda")
        msg.setText(help_text)
        msg.addButton("Aceptar", QMessageBox.AcceptRole)
        msg.exec()


    def check_updates_on_startup(self):
        """Run the update check on a worker and deliver the result by signal."""
        threading.Thread(target=self._check_updates_worker, daemon=True, name="update-check").start()

    def _check_updates_worker(self):
        try:
            update_info = VersionChecker.check_update()
        except Exception:
            update_info = None
        try:
            self._update_ready.emit(update_info)
        except RuntimeError:
            pass

    def _show_update(self, update_info):
        if not update_info:
            return
        try:
            newer = version.parse(update_info["latest"]) > version.parse(update_info["current"])
        except (KeyError, TypeError, ValueError):
            return
        if not newer:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Actualización disponible")
        msg.setText(
            f"Hay una nueva versión disponible: {update_info['latest']}\n\n"
            f"Versión actual: {update_info['current']}\n\n"
            "¿Quieres abrir la página de descarga?"
        )

        # Use standard buttons for better compatibility
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        msg.button(QMessageBox.Yes).setText("Sí")
        msg.button(QMessageBox.No).setText("No")

        if msg.exec() == QMessageBox.Yes:
            QDesktopServices.openUrl(update_info["url"])

    def open_live_monitor(self):
        QDesktopServices.openUrl("https://livecenter.tiktok.com/live_monitor?lang=es-ES")

    def handle_ui_update(self):
        self.load_account_info()

def main():
    app = QApplication(sys.argv)
    instance = SingleInstance(instance_key())
    if not instance.acquire():
        if not instance.notify_existing():
            QMessageBox.information(None, "FPV Stream", "Ya hay otra instancia abierta.")
        return 0
    try:
        window = StreamApp()

        def activate():
            window.showNormal()
            window.raise_()
            window.activateWindow()

        instance.on_activation(activate)
        window.show()
        return app.exec()
    finally:
        instance.close()


if __name__ == "__main__":
    sys.exit(main())
