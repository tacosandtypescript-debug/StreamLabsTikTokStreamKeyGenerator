"""Construction of the widgets that make up the main window.

The window is laid out as one screen with a clear state: a banner that says what
is going on, two cards with the work to do (the stream and the connection), a
foldable section with the account and the token, and a status bar that shows
progress and keeps the secondary actions out of the way.

Every widget keeps the attribute name it had before the redesign, so the rest of
the application (and its tests) did not have to change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import application_icon, eye_icon
from ui.theme import color_tokens, current_theme
from ui.widgets import (
    CollapsibleSection,
    CopyField,
    FadingProgressBar,
    HeightAnimator,
    StateBanner,
)

# The suggestion list has no content-based height, so it gets an explicit one.
SUGGESTIONS_HEIGHT = 120


class WindowUiMixin:
    def init_ui(self) -> None:
        self.setWindowTitle("Generador de clave de TikTok Live (vía Streamlabs)")
        # Small enough to fit a laptop screen; the body scrolls if it has to.
        self.setMinimumSize(720, 540)
        icon = application_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(14, 14, 14, 8)
        outer.setSpacing(10)

        self.banner = StateBanner()
        outer.addWidget(self.banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        body_layout.addLayout(cards)

        cards.addWidget(self._build_stream_card(), 3)
        cards.addWidget(self._build_connection_card(), 2)
        body_layout.addLayout(cards)
        body_layout.addWidget(self._build_account_section())
        # Everything that is left over stays at the bottom, so the cards keep the
        # height of their content instead of stretching to fill the window.
        body_layout.addStretch(1)

        self._build_status_bar()
        self._set_status("Sin token")

    # ------------------------------------------------------------------ cards

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        # Maximum, so a card never eats the empty space of the window: it is as
        # tall as its content and the slack goes to the stretch at the bottom.
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        return card, layout

    @staticmethod
    def _field_label(text: str, buddy: QWidget | None = None) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        if buddy is not None:
            label.setBuddy(buddy)
        return label

    def _build_stream_card(self) -> QFrame:
        card, layout = self._card("Directo")

        self.stream_title = QLineEdit()
        self.stream_title.setToolTip("El título que tendrá el directo en TikTok")
        self.stream_title.textChanged.connect(lambda _text: self._update_controls())
        layout.addWidget(self._field_label("&Título del directo", self.stream_title))
        layout.addWidget(self.stream_title)

        self.game_category = QLineEdit()
        self.game_category.setToolTip("Escribe para buscar; elige una sugerencia de la lista")
        self.game_category.textChanged.connect(self.handle_game_search)
        layout.addWidget(self._field_label("&Categoría", self.game_category))
        layout.addWidget(self.game_category)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setMaximumHeight(0)
        self.suggestions_list.hide()
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        self._suggestions_animator = HeightAnimator(
            self.suggestions_list,
            natural_height=SUGGESTIONS_HEIGHT,
        )
        layout.addWidget(self.suggestions_list)

        self.mature_checkbox = QCheckBox("Contenido para adultos")
        self.mature_checkbox.setToolTip("Marca la sesión como contenido para adultos")
        self.mature_checkbox.stateChanged.connect(lambda _state: self._update_controls())
        layout.addWidget(self.mature_checkbox)
        layout.addSpacing(8)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.go_live_btn = QPushButton("Preparar directo")
        self.go_live_btn.setObjectName("primary")
        self.go_live_btn.setToolTip(
            "Pide a Streamlabs que prepare la sesión y devuelve la URL y la clave"
        )
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.clicked.connect(lambda _checked=False: self.start_stream())
        actions.addWidget(self.go_live_btn)

        self.end_live_btn = QPushButton("Finalizar directo")
        self.end_live_btn.setToolTip(
            "Detén primero la salida de TikTok en OBS y después cierra la sesión de Streamlabs"
        )
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.clicked.connect(lambda _checked=False: self.end_stream())
        actions.addWidget(self.end_live_btn)
        actions.addStretch(1)

        self.save_btn = QPushButton("Guardar configuración")
        self.save_btn.setToolTip("Guarda el título, la categoría y las preferencias (sin secretos)")
        self.save_btn.clicked.connect(lambda _checked=False: self.save_config())
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)
        return card

    def _build_connection_card(self) -> QFrame:
        card, layout = self._card("Conexión")

        self.stream_url = CopyField(placeholder="Aparecerá al preparar el directo")
        self.stream_url.copied.connect(lambda: self.copy_to_clipboard(self.stream_url, False))
        self.copy_url_btn = self.stream_url.copy_button
        layout.addWidget(self._field_label("URL del servidor", self.stream_url.line_edit))
        layout.addWidget(self.stream_url)

        self.stream_key = CopyField(
            sensitive=True,
            revealable=True,
            placeholder="Aparecerá al preparar el directo",
        )
        self.stream_key.copied.connect(lambda: self.copy_to_clipboard(self.stream_key, True))
        self.copy_key_btn = self.stream_key.copy_button
        layout.addWidget(
            self._field_label("Clave de retransmisión", self.stream_key.line_edit)
        )
        layout.addWidget(self.stream_key)

        note = QLabel("La clave se retira del portapapeles a los 60 segundos.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return card

    def _build_account_section(self) -> CollapsibleSection:
        self.account_section = CollapsibleSection("Cuenta y token", expanded=True)
        self.account_section.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        layout = self.account_section.body.layout()

        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Pega aquí el token o cárgalo con los botones…")
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.textChanged.connect(lambda _text: self.handle_token_change())
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        layout.addWidget(self._field_label("&Token de Streamlabs", self.token_entry))

        token_row = QHBoxLayout()
        token_row.setSpacing(4)
        token_row.addWidget(self.token_entry, 1)
        self.toggle_token_btn = QToolButton()
        self.toggle_token_btn.setAutoRaise(True)
        self.toggle_token_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_token_btn.clicked.connect(
            lambda _checked=False: self.toggle_token_visibility()
        )
        self._set_token_reveal_button(False)
        token_row.addWidget(self.toggle_token_btn)
        layout.addLayout(token_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.load_local_btn = QPushButton("Cargar desde el PC")
        self.load_local_btn.setToolTip(
            "Lee el token que Streamlabs Desktop tiene guardado en este equipo"
        )
        self.load_local_btn.clicked.connect(self.load_local_token)
        buttons.addWidget(self.load_local_btn)

        self.load_online_btn = QPushButton("Iniciar sesión web")
        self.load_online_btn.setToolTip("Obtiene el token con el inicio de sesión de Streamlabs")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        buttons.addWidget(self.load_online_btn)

        self.save_token_btn = QPushButton("Guardar token de forma segura")
        self.save_token_btn.setToolTip(
            "Guarda el token validado en el almacén de credenciales del sistema"
        )
        self.save_token_btn.clicked.connect(
            lambda _checked=False: self.save_token_securely()
        )
        buttons.addWidget(self.save_token_btn)
        layout.addLayout(buttons)

        self.refresh_btn = QPushButton("Actualizar datos de la cuenta")
        self.refresh_btn.setToolTip(
            "Vuelve a consultar el usuario, el estado y el permiso de emisión"
        )
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_account_info())
        layout.addWidget(self.refresh_btn)

        info = QHBoxLayout()
        info.setSpacing(16)
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setMinimumWidth(160)
        username_column = QVBoxLayout()
        username_column.setSpacing(4)
        username_column.addWidget(self._field_label("Usuario", self.tiktok_username))
        username_column.addWidget(self.tiktok_username)
        info.addLayout(username_column, 1)

        self.can_go_live = QLabel("—")
        self.can_go_live.setObjectName("badge")
        self.can_go_live.setProperty("state", "neutral")
        live_column = QVBoxLayout()
        live_column.setSpacing(4)
        live_column.addWidget(self._field_label("Puede emitir"))
        live_column.addWidget(self.can_go_live)
        live_column.addStretch(1)
        info.addLayout(live_column, 0)
        layout.addLayout(info)
        return self.account_section

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)

        self.app_status = QLabel("Sin token")
        self.app_status.setObjectName("statusText")
        status.addWidget(self.app_status, 1)

        self.progress = FadingProgressBar()
        status.addPermanentWidget(self.progress)

        self.support_btn = QToolButton()
        self.support_btn.setText("Más")
        self.support_btn.setToolTip("Ayuda, registros, informe y enlaces")
        self.support_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.support_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # The popup indicator is drawn next to the text, which used to clip it.
        self.support_btn.setMinimumWidth(72)
        menu = QMenu(self.support_btn)
        menu.addAction("Abrir la carpeta de registros", self.open_logs_folder)
        menu.addAction("Guardar informe de diagnóstico", self.export_diagnostics)
        menu.addSeparator()
        self.help_btn = menu.addAction("Ayuda", self.show_help)
        self.monitor_btn = menu.addAction("Abrir monitor de TikTok", self.open_live_monitor)
        self.donate_btn = menu.addAction("Donar al autor original", self.open_donation_page)
        self.support_btn.setMenu(menu)
        status.addPermanentWidget(self.support_btn)

    # ---------------------------------------------------------------- helpers

    def _set_token_reveal_button(self, visible: bool) -> None:
        tokens = color_tokens(current_theme())
        self.toggle_token_btn.setIcon(eye_icon(16, tokens["text"], open_eye=not visible))
        self.toggle_token_btn.setToolTip("Ocultar el token" if visible else "Mostrar el token")

    def _set_suggestions_visible(self, visible: bool) -> None:
        if visible:
            self._suggestions_animator.expand()
        else:
            self._suggestions_animator.collapse()

    def _set_banner(
        self,
        state: str,
        headline: str,
        detail: str = "",
    ) -> None:
        self.banner.set_state(state, headline, detail)
