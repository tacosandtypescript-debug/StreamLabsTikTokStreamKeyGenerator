"""Construction of the widgets that make up the main window."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import application_icon


class WindowUiMixin:
    def init_ui(self) -> None:
        self.setWindowTitle("Generador de clave de TikTok Live (vía Streamlabs)")
        self.setMinimumSize(800, 600)
        icon = application_icon()
        if icon is not None:
            self.setWindowIcon(icon)

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

        # One entry point for the support actions: a row of six buttons does not
        # fit next to the donation and monitor ones.
        self.support_btn = QToolButton()
        self.support_btn.setText("Soporte")
        self.support_btn.setToolTip("Registros e informe de diagnóstico")
        self.support_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        support_menu = QMenu(self.support_btn)
        support_menu.addAction("Abrir la carpeta de registros", self.open_logs_folder)
        support_menu.addAction("Guardar informe de diagnóstico", self.export_diagnostics)
        self.support_btn.setMenu(support_menu)
        bottom_buttons.addWidget(self.support_btn)

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
