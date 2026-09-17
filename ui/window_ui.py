"""Construction of the widgets that make up the main window.

The window is deliberately small and **fixed**: it is exactly as big as its
content needs, it cannot be resized and it has no empty surface to fill. Because
a fixed window cannot grow, the occasional part (the account and the token) lives
on a second page inside the same window, reached with one button and a fade. The
everyday screen keeps only what is used before every stream.

Every widget keeps the attribute name it had before, so the rest of the
application (and its tests) did not have to change.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import application_icon, eye_icon
from ui.theme import color_tokens, current_theme
from ui.widgets import (
    ANIMATION_MS,
    CopyField,
    FadingProgressBar,
    HeightAnimator,
    StateBanner,
)

# The suggestion list has no content-based height, so it gets an explicit one.
SUGGESTIONS_HEIGHT = 120
PAGE_STREAM = 0
PAGE_ACCOUNT = 1
OUTER_MARGIN = 12
# Narrower than this and an RTMP URL stops being readable, so the fixed width has
# a floor even though Qt would happily shrink the window to its minimum.
MINIMUM_CONTENT_WIDTH = 480


class WindowUiMixin:
    def init_ui(self) -> None:
        self.setWindowTitle("Generador de clave de TikTok Live (vía Streamlabs)")
        # Fixed size: there is nothing to arrange and nothing to stretch, so the
        # window has no reason to be resized or maximized.
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
        icon = application_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(OUTER_MARGIN, OUTER_MARGIN, OUTER_MARGIN, 8)
        outer.setSpacing(10)

        self.banner = StateBanner()
        outer.addWidget(self.banner)

        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.stream_page = self._build_stream_page()
        self.account_page = self._build_account_page()
        self.pages.addWidget(self.stream_page)
        self.pages.addWidget(self.account_page)

        self._build_status_bar()
        self._set_status("Sin token")

        # A persistent effect per page, so the fade has a stable target and no
        # animation can outlive what it animates.
        self._page_animation: QPropertyAnimation | None = None
        for page in (self.stream_page, self.account_page):
            effect = QGraphicsOpacityEffect(page)
            effect.setOpacity(1.0)
            page.setGraphicsEffect(effect)

        self._apply_fixed_size()

    # ------------------------------------------------------------------ pages

    def current_page(self) -> int:
        """Return the page on screen: ``PAGE_STREAM`` or ``PAGE_ACCOUNT``."""

        return self.pages.currentIndex()

    def show_account_page(self) -> None:
        self._switch_page(PAGE_ACCOUNT)

    def show_stream_page(self) -> None:
        self._switch_page(PAGE_STREAM)

    def _switch_page(self, index: int) -> None:
        if self.pages.currentIndex() == index:
            return
        self.pages.setCurrentIndex(index)
        effect = self.pages.currentWidget().graphicsEffect()
        if effect is None:  # pragma: no cover - the effects are created above
            return
        if self._page_animation is not None:
            self._page_animation.stop()
            self._page_animation.deleteLater()
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(ANIMATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        self._page_animation = animation
        animation.start()

    def _apply_fixed_size(self) -> None:
        """Freeze the window at the size its content asks for.

        Both pages are measured, so the taller one fits without clipping, and the
        size follows the system font: a large font gives a larger window instead
        of cut-off labels.
        """

        sizes = []
        for index in (PAGE_STREAM, PAGE_ACCOUNT):
            self.pages.setCurrentIndex(index)
            self.adjustSize()
            sizes.append(self.size())
        self.pages.setCurrentIndex(PAGE_STREAM)
        self.setFixedSize(
            max(max(size.width() for size in sizes), MINIMUM_CONTENT_WIDTH),
            max(size.height() for size in sizes),
        )

    # ------------------------------------------------------------------ cards

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
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

    def _build_stream_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        stream_card, stream_layout = self._card("Directo")
        self.stream_title = QLineEdit()
        self.stream_title.setToolTip("El título que tendrá el directo en TikTok")
        self.stream_title.textChanged.connect(lambda _text: self._update_controls())
        stream_layout.addWidget(self._field_label("&Título del directo", self.stream_title))
        stream_layout.addWidget(self.stream_title)

        self.game_category = QLineEdit()
        self.game_category.setToolTip("Escribe para buscar; elige una sugerencia de la lista")
        self.game_category.textChanged.connect(self.handle_game_search)
        stream_layout.addWidget(self._field_label("&Categoría", self.game_category))
        stream_layout.addWidget(self.game_category)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setMaximumHeight(0)
        self.suggestions_list.hide()
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        self._suggestions_animator = HeightAnimator(
            self.suggestions_list,
            natural_height=SUGGESTIONS_HEIGHT,
        )
        stream_layout.addWidget(self.suggestions_list)

        self.mature_checkbox = QCheckBox("Contenido para adultos")
        self.mature_checkbox.setToolTip("Marca la sesión como contenido para adultos")
        self.mature_checkbox.stateChanged.connect(lambda _state: self._update_controls())
        stream_layout.addWidget(self.mature_checkbox)
        layout.addWidget(stream_card)

        connection_card, connection_layout = self._card("Conexión")
        self.stream_url = CopyField(placeholder="Aparecerá al preparar el directo")
        self.stream_url.copied.connect(lambda: self.copy_to_clipboard(self.stream_url, False))
        self.copy_url_btn = self.stream_url.copy_button
        connection_layout.addWidget(
            self._field_label("URL del servidor", self.stream_url.line_edit)
        )
        connection_layout.addWidget(self.stream_url)

        self.stream_key = CopyField(
            sensitive=True,
            revealable=True,
            placeholder="Aparecerá al preparar el directo",
        )
        self.stream_key.copied.connect(lambda: self.copy_to_clipboard(self.stream_key, True))
        self.copy_key_btn = self.stream_key.copy_button
        connection_layout.addWidget(
            self._field_label("Clave de retransmisión", self.stream_key.line_edit)
        )
        connection_layout.addWidget(self.stream_key)

        note = QLabel("La clave se retira del portapapeles a los 60 segundos.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        connection_layout.addWidget(note)
        layout.addWidget(connection_card)

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

        self.save_btn = QPushButton("Guardar datos")
        self.save_btn.setToolTip(
            "Guarda el título, la categoría y las preferencias (sin secretos)"
        )
        self.save_btn.clicked.connect(lambda _checked=False: self.save_config())
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

        self.account_btn = QPushButton("Cuenta y token")
        self.account_btn.setObjectName("link")
        self.account_btn.setToolTip("Token de Streamlabs, usuario y permiso de emisión")
        self.account_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_btn.clicked.connect(self.show_account_page)
        layout.addWidget(self.account_btn)
        layout.addStretch(1)
        return page

    def _build_account_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        token_card, token_layout = self._card("Cuenta de Streamlabs")
        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Pega aquí el token o cárgalo con los botones…")
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.textChanged.connect(lambda _text: self.handle_token_change())
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_layout.addWidget(self._field_label("T&oken de Streamlabs", self.token_entry))

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
        token_layout.addLayout(token_row)

        load_buttons = QHBoxLayout()
        load_buttons.setSpacing(8)
        self.load_local_btn = QPushButton("Cargar desde el PC")
        self.load_local_btn.setToolTip(
            "Lee el token que Streamlabs Desktop tiene guardado en este equipo"
        )
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons.addWidget(self.load_local_btn)

        self.load_online_btn = QPushButton("Iniciar sesión web")
        self.load_online_btn.setToolTip("Obtiene el token con el inicio de sesión de Streamlabs")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons.addWidget(self.load_online_btn)
        token_layout.addLayout(load_buttons)

        self.refresh_btn = QPushButton("Actualizar datos de la cuenta")
        self.refresh_btn.setToolTip(
            "Vuelve a consultar el usuario, el estado y el permiso de emisión"
        )
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_account_info())
        token_layout.addWidget(self.refresh_btn)

        self.save_token_btn = QPushButton("Guardar token de forma segura")
        self.save_token_btn.setToolTip(
            "Guarda el token validado en el almacén de credenciales del sistema"
        )
        self.save_token_btn.clicked.connect(lambda _checked=False: self.save_token_securely())
        token_layout.addWidget(self.save_token_btn)
        layout.addWidget(token_card)

        account_card, account_layout = self._card("Permiso de emisión")
        self.tiktok_username = QLineEdit()
        self.tiktok_username.setReadOnly(True)
        self.tiktok_username.setPlaceholderText("Sin validar")
        account_layout.addWidget(self._field_label("Usuario", self.tiktok_username))
        account_layout.addWidget(self.tiktok_username)

        self.can_go_live = QLabel("—")
        self.can_go_live.setObjectName("badge")
        self.can_go_live.setProperty("state", "neutral")
        account_layout.addWidget(self._field_label("Puede emitir"))
        account_layout.addWidget(self.can_go_live)
        layout.addWidget(account_card)

        hint = QLabel(
            "El token se guarda cifrado en el almacén del sistema, nunca en config.json."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        back_row = QHBoxLayout()
        self.back_btn = QPushButton("Volver al directo")
        self.back_btn.setToolTip("Vuelve a la pantalla del directo")
        self.back_btn.clicked.connect(self.show_stream_page)
        back_row.addWidget(self.back_btn)
        back_row.addStretch(1)
        layout.addLayout(back_row)
        layout.addStretch(1)
        return page

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
        self.support_btn.setMinimumWidth(64)
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

    def _set_banner(self, state: str, headline: str, detail: str = "") -> None:
        self.banner.set_state(state, headline, detail)
