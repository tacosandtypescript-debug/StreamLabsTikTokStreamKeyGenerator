import glob
import os
import platform
import re
import sys
import json
import threading
import traceback
import hashlib
import tempfile
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QGroupBox, QPushButton, QLineEdit, QLabel, QCheckBox,
                              QListWidget, QMessageBox, QListWidgetItem, QSizePolicy)
from PySide6.QtCore import Signal, QTimer, Qt
from PySide6.QtGui import QDesktopServices
from Stream import Stream
from TokenRetriever import TokenRetriever
from Updater import VersionChecker
from packaging import version

class StreamApp(QMainWindow):
    update_suggestions = Signal(list)
    update_ui = Signal()
    _token_ready = Signal(str)
    _token_error = Signal(str)
    _restore_local_btn = Signal()
    _online_done = Signal(object)
    _api_done = Signal(object)
    _search_done = Signal(object)

    def __init__(self, *, startup_checks=True):
        super().__init__()
        self.stream = None
        self.game_mask_id = ""
        self.live_state = "offline"
        self._api_busy = False
        self._pending_operation = None
        self._client_token = ""
        self._can_go_live = False
        self._saved_session = None
        self._online_retriever = None
        self._search_generation = 0
        self._search_inflight = False
        self._categories = {}
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._dispatch_search)
        self.init_ui()
        
        if startup_checks:
            QTimer.singleShot(3000, lambda: [
                self.show_donation_reminder(),
                QTimer.singleShot(3000, self.check_updates_on_startup)
            ])

        # Connect signals
        self.update_suggestions.connect(self.update_suggestions_list)
        self.update_ui.connect(self.handle_ui_update)
        self._token_ready.connect(self._apply_token)
        self._token_error.connect(lambda msg: QMessageBox.critical(self, "Error", msg))
        self._restore_local_btn.connect(self._do_restore_local_btn)
        self._online_done.connect(self._finish_online_token)
        self._api_done.connect(self._finish_api)
        self._search_done.connect(self._finish_search)
        self.load_config()

    def init_ui(self):
        self.setWindowTitle("StreamLabs TikTok Stream Key Generator")
        self.setMinimumSize(800, 600)

        main_widget = QWidget()
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Left column
        left_column = QVBoxLayout()
        main_layout.addLayout(left_column)

        # Token Section
        token_group = QGroupBox("Token Loader")
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
        self.token_entry.setPlaceholderText("Paste token here or load below...")
        self.token_entry.setEchoMode(QLineEdit.Password)
        self.token_entry.setFixedHeight(28)
        self.token_entry.textChanged.connect(self.handle_token_change)
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_entry_row.addWidget(self.token_entry)

        # Eye icon for password visibility
        self.toggle_token_btn = QPushButton()
        self.toggle_token_btn.setFixedSize(28, 28)
        self.toggle_token_btn.setText("👁️")
        self.toggle_token_btn.setToolTip("Show token")
        self.toggle_token_btn.clicked.connect(self.toggle_token_visibility)
        token_entry_row.addWidget(self.toggle_token_btn)

        token_layout.addLayout(token_entry_row)

        # Token Load Buttons Row
        load_buttons_row = QHBoxLayout()
        load_buttons_row.setSpacing(5)

        # Local Token Button
        self.load_local_btn = QPushButton("Load from PC")
        self.load_local_btn.setFixedHeight(30)
        self.load_local_btn.setToolTip("Load token from Streamlabs desktop app data")
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons_row.addWidget(self.load_local_btn)

        # Online Token Button
        self.load_online_btn = QPushButton("Load from Web")
        self.load_online_btn.setFixedHeight(30)
        self.load_online_btn.setToolTip("Get token through browser login")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons_row.addWidget(self.load_online_btn)
        self.cancel_login_btn = QPushButton("Cancelar")
        self.cancel_login_btn.setFixedHeight(30)
        self.cancel_login_btn.setEnabled(False)
        self.cancel_login_btn.clicked.connect(self.cancel_online_login)
        load_buttons_row.addWidget(self.cancel_login_btn)

        token_layout.addLayout(load_buttons_row)
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
            self.binary_location_entry.setPlaceholderText("Custom Chrome binary path (optional)")
            self.binary_location_entry.setFixedHeight(28)
            self.binary_location_entry.setToolTip("Leave empty to auto-detect Chrome path on Linux")
            binary_row.addWidget(self.binary_location_entry)
            
            token_layout.addLayout(binary_row)


        # Account Info Section
        account_info_label = QLabel("Account Information")
        account_info_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        token_layout.addWidget(account_info_label)

        # Username
        username_row = QHBoxLayout()
        username_row.setSpacing(5)
        username_label = QLabel("Username:")
        username_label.setFixedWidth(100)
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setFixedHeight(26)
        username_row.addWidget(username_label)
        username_row.addWidget(self.tiktok_username)
        token_layout.addLayout(username_row)

        # Status
        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        status_label = QLabel("Status:")
        status_label.setFixedWidth(100)
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
        live_label = QLabel("Can Go Live:")
        live_label.setFixedWidth(100)
        self.can_go_live = QLineEdit()
        self.can_go_live.setReadOnly(True)
        self.can_go_live.setToolTip("Permiso para preparar una sesión; no confirma que TikTok reciba vídeo.")
        self.can_go_live.setFixedHeight(26)
        live_row.addWidget(live_label)
        live_row.addWidget(self.can_go_live)
        token_layout.addLayout(live_row)
        
        # Refresh account info button
        refresh_btn = self.refresh_btn = QPushButton("Refresh Account Info")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setToolTip("Refresh account information")
        refresh_btn.clicked.connect(self.refresh_account_info)
        token_layout.addWidget(refresh_btn)

        # Add stretch to prevent expansion
        token_layout.addStretch()

        # Stream Details
        stream_group = QGroupBox("Stream Details")
        left_column.addWidget(stream_group)
        stream_layout = QVBoxLayout()
        stream_layout.setContentsMargins(8, 8, 8, 8)  # Left, Top, Right, Bottom margins
        stream_layout.setSpacing(5)  # Reduced spacing between widgets
        stream_group.setLayout(stream_layout)

        # Stream Title
        title_label = QLabel("Stream Title:")
        title_label.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(title_label)
        self.stream_title = QLineEdit()
        self.stream_title.setFixedHeight(28)  # Slightly smaller height
        stream_layout.addWidget(self.stream_title)

        # Game Category
        game_label = QLabel("Game Category:")
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
        self.mature_checkbox = QCheckBox("Enable mature content")
        self.mature_checkbox.setStyleSheet("padding: 2px;")  # Reduce internal padding
        stream_layout.addWidget(self.mature_checkbox)

        # Add stretch to push everything up
        stream_layout.addStretch()

        # Right column (Controls)
        control_group = QGroupBox("Stream Control")
        control_group.setMinimumWidth(250)  # Set a minimum width for the control column
        main_layout.addWidget(control_group)

        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(8, 12, 8, 8)  # Tighter margins
        control_layout.setSpacing(6)  # Reduced spacing between widgets
        control_group.setLayout(control_layout)

        # Buttons row
        button_row = QHBoxLayout()
        button_row.setSpacing(5)  # Tight spacing between buttons

        self.go_live_btn = QPushButton("Go Live")
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.clicked.connect(self.start_stream)
        self.go_live_btn.setFixedHeight(32)  # Consistent button height
        button_row.addWidget(self.go_live_btn)

        self.end_live_btn = QPushButton("End Live")
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.clicked.connect(self.end_stream)
        self.end_live_btn.setFixedHeight(32)
        button_row.addWidget(self.end_live_btn)

        control_layout.addLayout(button_row)

        self.live_status = QLabel("Sin sesión preparada en este generador")
        self.live_status.setStyleSheet("color: #595959; font-weight: bold;")
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
        url_label = QLabel("Stream URL:")
        url_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(url_label)

        self.stream_url = QLineEdit()
        self.stream_url.setReadOnly(True)
        self.stream_url.setFixedHeight(28)  # Compact height
        control_layout.addWidget(self.stream_url)

        self.copy_url_btn = QPushButton("Copy URL")
        self.copy_url_btn.setFixedHeight(28)
        self.copy_url_btn.clicked.connect(lambda: self.copy_to_clipboard(self.stream_url))
        control_layout.addWidget(self.copy_url_btn)

        # Key Section
        key_label = QLabel("Stream Key:")
        key_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        control_layout.addWidget(key_label)

        self.stream_key = QLineEdit()
        self.stream_key.setReadOnly(True)
        self.stream_key.setEchoMode(QLineEdit.Password)
        self.stream_key.setFixedHeight(28)
        control_layout.addWidget(self.stream_key)

        self.copy_key_btn = QPushButton("Copy Key")
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

        self.save_btn = QPushButton("Save Config")
        self.save_btn.clicked.connect(lambda: self.save_config())
        bottom_buttons.addWidget(self.save_btn)

        self.help_btn = QPushButton("Help")
        self.help_btn.clicked.connect(self.show_help)
        bottom_buttons.addWidget(self.help_btn)
        
        self.donate_btn = QPushButton("☕ Donate")
        self.donate_btn.setToolTip("Support the developer")
        self.donate_btn.clicked.connect(lambda: QDesktopServices.openUrl("https://buymeacoffee.com/loukious"))
        bottom_buttons.addWidget(self.donate_btn)

        self.monitor_btn = QPushButton("Open Live Monitor")
        self.monitor_btn.clicked.connect(self.open_live_monitor)
        bottom_buttons.addWidget(self.monitor_btn)

    def toggle_token_visibility(self):
        """Toggle token visibility and update emoji"""
        if self.token_entry.echoMode() == QLineEdit.Normal:
            self.token_entry.setEchoMode(QLineEdit.Password)
            self.toggle_token_btn.setText("👁️")  # Closed eye
            self.toggle_token_btn.setToolTip("Show token")
        else:
            self.token_entry.setEchoMode(QLineEdit.Normal)
            self.toggle_token_btn.setText("👁️‍🗨️")  # Eye with speech bubble (visible)
            self.toggle_token_btn.setToolTip("Hide token")

    def handle_token_change(self):
        self._sync_controls()

    def _set_live_state(self, state, detail=""):
        self.live_state = state
        labels = {
            "starting": ("Creando sesión de TikTok…", "color: #8a5200; font-weight: bold;"),
            "prepared": ("Sesión de TikTok preparada", "color: #8a5200; font-weight: bold;"),
            "uncertain": ("Estado de la sesión sin confirmar", "color: #8a5200; font-weight: bold;"),
            "ending": ("Solicitando cierre de la sesión…", "color: #8a5200; font-weight: bold;"),
            "offline": ("Sin sesión preparada en este generador", "color: #595959; font-weight: bold;"),
            "error": ("Error de sesión", "color: #b00020; font-weight: bold;"),
        }
        text, style = labels.get(state, labels["error"])
        self.live_status.setText(f"{text}{(' — ' + detail) if detail else ''}")
        self.live_status.setStyleSheet(style)
        self._sync_controls()

    def load_config(self):
        try:
            with open("config.json", "r") as file:
                data = json.load(file)
        except:
            data = {}
        self._saved_session = data.get("session")
        self.token_entry.setText(data.get("token", ""))
        self.stream_title.setText(data.get("title", ""))
        self.game_category.setText(data.get("game", ""))
        self.mature_checkbox.setChecked(data.get("audience_type", "0") == "1")
        self.suppress_donation_reminder = data.get("suppress_donation_reminder", False)

        self.refresh_account_info()

    def save_config(self, show_message=True):
        data = {
            "title": self.stream_title.text(),
            "game": self.game_category.text(),
            "audience_type": "1" if self.mature_checkbox.isChecked() else "0",
            "token": self.token_entry.text(),
            "suppress_donation_reminder": self.suppress_donation_reminder
        }
        if self.stream and (self.stream.id or self.stream.session_uncertain or
                            self._api_busy and self._pending_operation in ("start", "end")):
            data["session"] = {"id": self.stream.id, "uncertain": self.stream.session_uncertain or self._api_busy,
                               "account": hashlib.sha256(self._client_token.encode()).hexdigest()}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=".", prefix=".config-", suffix=".json", delete=False) as file:
                temporary = file.name
                json.dump(data, file)
            os.replace(temporary, "config.json")
        except OSError:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            self.live_status.setText("No se pudo guardar el estado local. Comprueba los permisos de la carpeta.")
            return False
        if show_message:
            QMessageBox.information(self, "Config Saved", "Configuration saved successfully!")
        return True

    def _sync_controls(self):
        known = bool(self.stream and self.stream.id)
        uncertain = bool(self.stream and self.stream.session_uncertain)
        login_pending = self._online_retriever is not None
        locked = self._api_busy or known or uncertain or login_pending
        current_account = bool(self.stream and self._client_token == self.token_entry.text().strip())
        self.go_live_btn.setEnabled(current_account and self._can_go_live and not locked)
        self.end_live_btn.setEnabled(known and not self._api_busy)
        self.token_entry.setEnabled(not locked)
        self.load_local_btn.setEnabled(not locked)
        self.load_online_btn.setEnabled(not locked)
        self.cancel_login_btn.setEnabled(login_pending)
        self.load_online_btn.setText("Esperando sesión…" if login_pending else "Load from Web")
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
                self.tiktok_username.setText(str(user.get("username", "Unknown")) if isinstance(user, dict) else "Unknown")
                self.app_status.setText(str(application.get("status", "Unknown")) if isinstance(application, dict) else "Unknown")
                self.can_go_live.setText(str(self._can_go_live))
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
                self._set_live_state("uncertain", error or "No se confirmó el cierre. Revisa Live Monitor o reintenta End Live.")
        self.save_config(False)
        self._sync_controls()

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

    def _do_restore_local_btn(self):
        self.load_local_btn.setText("Load from PC")
        self._sync_controls()

    def load_local_token(self):
        self.load_local_btn.setEnabled(False)
        self.load_local_btn.setText("Searching…")

        def _run():
            try:
                token = self._find_local_token()
            except Exception as e:
                print(traceback.format_exc())
                self._token_error.emit(f"Unexpected error: {e}")
                return
            finally:
                self._restore_local_btn.emit()

            if token:
                self._token_ready.emit(token)
            else:
                self._token_error.emit(
                    "No API Token found locally. Make sure Streamlabs is installed "
                    "and you're logged in using TikTok."
                )

        threading.Thread(target=_run, daemon=True).start()

    def _find_local_token(self) -> str | None:
        """Blocking file scan — runs on a worker thread."""
        if platform.system() == 'Windows':
            path_pattern = os.path.expandvars(
                r'%appdata%\slobs-client\Local Storage\leveldb\*.log'
            )
        elif platform.system() == 'Darwin':
            path_pattern = os.path.expanduser(
                '~/Library/Application Support/slobs-client/Local Storage/leveldb/*.log'
            )
        else:
            QTimer.singleShot(0, lambda: QMessageBox.critical(
                self, "Error", "Unsupported operating system for local token retrieval."
            ))
            return None

        files = sorted(glob.glob(path_pattern), key=os.path.getmtime, reverse=True)
        token_pattern = re.compile(r'"apiToken":"([a-f0-9]+)"', re.IGNORECASE)

        for file in files:
            try:
                with open(file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='ignore')
                content = re.sub(r'[\x00]', '', content)
                matches = token_pattern.findall(content)
                if matches:
                    return matches[-1]
            except Exception as e:
                print(f"Error reading {file}: {e}")

        return None

    def fetch_online_token(self):
        if self._online_retriever or self._api_busy or self.stream and (self.stream.id or self.stream.session_uncertain):
            return
        retriever = TokenRetriever()
        self._online_retriever = retriever
        self.login_status.setText("Completa el inicio de sesión en el navegador o pulsa Cancelar.")
        self._sync_controls()

        def _run():
            token = None
            try:
                # Match upstream: Python's default browser opener runs on the
                # worker, keeping shell/browser launch off the GUI thread.
                token = retriever.retrieve_token()
            except Exception:
                retriever.last_error = "No se pudo iniciar la sesión web. Puedes reintentar."
            finally:
                try:
                    self._online_done.emit((retriever, token))
                except RuntimeError:
                    pass

        threading.Thread(target=_run, daemon=True, name="streamlabs-web-login").start()

    def cancel_online_login(self):
        retriever = self._online_retriever
        if retriever is None:
            return
        retriever.cancel()
        self._online_retriever = None
        self.login_status.setText("Inicio de sesión cancelado. Puedes reintentar.")
        self._sync_controls()

    def _finish_online_token(self, outcome):
        retriever, token = outcome
        # A cancelled attempt must never overwrite a later login's account.
        if retriever is not self._online_retriever:
            return
        self._online_retriever = None
        self._sync_controls()
        if token and not retriever.cancelled.is_set():
            self.login_status.setText("Inicio de sesión completado.")
            self._apply_token(token)
        else:
            self.login_status.setText(retriever.last_error or "No se completó el inicio de sesión. Puedes reintentar.")

    def _apply_token(self, token: str):
        """Apply a freshly retrieved token — always called on the GUI thread."""
        if self._api_busy or self.stream and (self.stream.id or self.stream.session_uncertain):
            return
        self.token_entry.setText(token)
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
        if client is not self.stream or generation != self._search_generation or query != self.game_category.text().strip():
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
        event.accept()

    def copy_to_clipboard(self, widget):
        QApplication.clipboard().setText(widget.text())
        QMessageBox.information(self, "Copied", "Text copied to clipboard!")

    def show_help(self):
        help_text = """1. Apply for LIVE access on Streamlabs
2. Install Streamlabs and login to TikTok
3. Use this app to get Streamlabs token
4. Go live!"""
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Help")
        msg.setText(help_text)
        msg.addButton(QMessageBox.Ok)
        msg.exec()


    def check_updates_on_startup(self):
        """Non-blocking update check with GUI notification"""
        update_info = VersionChecker.check_update()

        if update_info and version.parse(update_info["latest"]) > version.parse(update_info["current"]):
            msg = QMessageBox(self)
            msg.setWindowTitle("Update Available")
            msg.setText(
                f"Version {update_info['latest']} is available!\n\n"
                f"Current version: {update_info['current']}\n\n"
                "Would you like to download it now?"
            )
            
            # Use standard buttons for better compatibility
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.Yes)
            
            if msg.exec() == QMessageBox.Yes:
                QDesktopServices.openUrl(update_info["url"])

    def show_donation_reminder(self):
        
        if self.suppress_donation_reminder:
            return
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Support Development")
        msg.setText("Enjoying this app? Consider supporting its development!")
        
        dont_show_again = QCheckBox("Never show this message again")
        msg.setCheckBox(dont_show_again)
        
        # Add buttons
        donate_btn = msg.addButton("Donate Now", QMessageBox.AcceptRole)
        msg.addButton(QMessageBox.Ok)
        
        # Make the "Donate Now" button more prominent
        donate_btn.setStyleSheet("font-weight: bold;")
        
        # Execute the message box
        msg.exec()
        
        if dont_show_again.isChecked():
            self.suppress_donation_reminder = True
            self.save_config(False)
        # Handle button clicks
        if msg.clickedButton() == donate_btn:
            QDesktopServices.openUrl("https://buymeacoffee.com/loukious")

    def open_live_monitor(self):
        QDesktopServices.openUrl("https://livecenter.tiktok.com/live_monitor?lang=en-US")

    def handle_ui_update(self):
        self.load_account_info()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StreamApp()
    window.show()
    sys.exit(app.exec())
