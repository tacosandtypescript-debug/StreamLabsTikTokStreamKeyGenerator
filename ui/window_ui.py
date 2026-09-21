"""Construction of the widgets that make up the main window.

The window is **resizable**, but it does not need resizing: it opens at exactly the
size its content asks for, measured at the width it is going to have, and its
minimum is the size below which the cards would start clipping. So the default is
still "as big as its content", without the fixed window making every longer text
unreachable.

Everything is in **one column**: cards, fields and buttons are stacked, so the
window is narrow and tall — the shape that sits beside OBS — and the second page
already had that shape. The account and the token keep their own page inside the
same window, reached with one button and a fade.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.geometry import clamped_height
from ui.icons import (
    application_icon,
    eye_icon,
    key_icon,
    link_icon,
    play_icon,
    refresh_icon,
    save_icon,
    shield_icon,
    stop_icon,
    user_icon,
)
from ui.theme import color_tokens, current_theme
from ui.widgets import (
    ANIMATION_MS,
    ContentScrollArea,
    ContentStack,
    CopyField,
    FadingProgressBar,
    HeightAnimator,
    ProfileCard,
    StateBanner,
    StepsGuide,
    SummaryStrip,
)

# What a first run has to be told, in the order it has to be done. Each step is
# checked against state the window already holds, so the guide can never tick a step
# that is not actually done.
GUIDE_STEPS: tuple[tuple[str, str], ...] = (
    (
        "Carga el token de Streamlabs",
        "Pega el token, o consíguelo con «Iniciar sesión web».",
    ),
    (
        "Comprueba la cuenta",
        "Tiene que decir «Puede emitir: Sí». Si dice que no, ahí se explica el motivo.",
    ),
    (
        "Escribe título y categoría",
        "Elige una categoría de la lista que aparece al escribir.",
    ),
    (
        "Preparar directo",
        "La aplicación pedirá la sesión y te dará la URL y la clave.",
    ),
    (
        "Pega las dos en OBS y emite",
        "Ajustes → Emisión → Servicio: Personalizado. El estado cambia solo a EN VIVO.",
    ),
)

# The suggestion list has no content-based height, so it gets an explicit one.
SUGGESTIONS_HEIGHT = 120
PAGE_STREAM = 0
PAGE_ACCOUNT = 1
OUTER_MARGIN = 12
# Phone-shaped: narrow and tall, the way the account page already was. Narrower than
# this and the URL field starts hiding the address and the summary columns crowd each
# other; wider and it stops sitting comfortably beside OBS.
MINIMUM_CONTENT_WIDTH = 430
# The shortest the window may be made: below this the banner, the status bar and a
# sliver of the page would be all that is left. Deliberately *not* derived from the
# measured content, so that the window can always be shrunk and the pages scroll.
MINIMUM_WINDOW_HEIGHT = 360
# QWidget's "no limit", used while measuring the window again.
UNLIMITED_SIZE = 16777215


class WindowUiMixin:
    def init_ui(self) -> None:
        self.setWindowTitle("Generador de clave de TikTok Live (vía Streamlabs)")
        # Resizable: the maximize button is left in place on purpose, because a
        # user who wants the window out of the way can now do something about it.
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
        # One name for the account avatar, wherever it is shown.
        self.avatar = self.banner.avatar

        # The window is small and fixed, but its content grows with the system font
        # and can be taller than a short screen. The pages scroll when that happens,
        # and not at all when they fit: the stylesheet already draws the bar.
        self.scroll = ContentScrollArea()
        self.scroll.setObjectName("scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.pages = ContentStack()
        self.pages.setObjectName("scrollBody")
        self.scroll.setWidget(self.pages)
        outer.addWidget(self.scroll, 1)
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

        # The window is measured from here on, but not sized yet: the first
        # measurement happens before Qt has polished the widgets, so the labels have
        # not wrapped and the numbers are only close. ``showEvent`` takes the one
        # that counts.
        self._initial_size_applied = False
        self._apply_window_size()

    def showEvent(self, event: Any) -> None:
        """Size the window once, the first time it is shown.

        While the widgets are hidden Qt has not applied the final fonts and has not
        wrapped the labels, so a measurement taken then is only an approximation, and
        latching it in would open the window short and scroll over content that fits.
        The measurement that counts is the one taken as the window first appears.

        It must happen **only once**. Qt sends this event again whenever the window
        is shown after being hidden — restored from the taskbar, un-minimised — and
        resizing on those occasions would undo the size the user had chosen, which
        looked like the window growing by itself some seconds after being resized.
        """

        super().showEvent(event)
        if self._initial_size_applied:
            # Shown again after being hidden: the size is already the content's, so
            # there is nothing to redo and nothing to undo.
            return
        self._apply_window_size(initial=True)

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

    def _measure(self) -> tuple[int, int]:
        """Return the ``(width, height)`` this window's content asks for.

        Both pages are measured, so the taller one fits without clipping, and the
        size follows the system font. Each page is asked for the height it needs
        **at the width it is going to have**, because a height measured at another
        width is the wrong height: the wrapped labels wrap somewhere else.

        Measuring by resizing the window (``adjustSize``) was the obvious way and it
        was wrong twice over: it cannot grow a window whose maximum size is already
        fixed, and every measurement changes the state the next one reads, so the
        result depended on the order. This is arithmetic instead.
        """

        self.pages.setMinimumHeight(0)
        outer = self.centralWidget().layout()
        margins = outer.contentsMargins()
        inner_width = max(
            self.pages.sizeHint().width(),
            MINIMUM_CONTENT_WIDTH - margins.left() - margins.right(),
        )
        width = max(inner_width + margins.left() + margins.right(), MINIMUM_CONTENT_WIDTH)

        # Each page is measured while it is the one on screen: a hidden page has not
        # wrapped its labels yet and would answer short, which made the window change
        # size depending on which page was open.
        heights = []
        current = self.pages.currentIndex()
        for index in (PAGE_STREAM, PAGE_ACCOUNT):
            self.pages.setCurrentIndex(index)
            page = self.pages.widget(index)
            layout = page.layout() if page is not None else None
            if layout is not None:
                layout.activate()
            if page is not None:
                heights.append(self._page_height(page, inner_width))
        self.pages.setCurrentIndex(current)
        content_height = max(heights)
        return width, content_height + self._chrome_height()

    def _apply_window_size(self, *, initial: bool = False) -> None:
        """Fit the window to its content, and keep it there.

        The window is **fixed**: it is exactly as big as what it has to show, it
        grows on its own when the content grows — a validated account, a fetched
        biography, an opened suggestion list — and it is not something the user has
        to size. That is why it is measured again on every change instead of only
        once: a fixed window that forgot to re-measure would clip whatever arrived
        later.

        The result never exceeds what the screen offers: a 1080p laptop at 150% of
        scaling leaves about 690 logical pixels, and a window taller than the screen
        has a bottom nobody can reach. The pages scroll in that case, and not at all
        when they fit.
        """

        width, window_height = self._measure()
        available = self.available_height()

        # The floors are fixed, not measured. A minimum taken from the measured
        # content would rise as the window narrows, which would make the window
        # refuse to be narrowed at all.
        self.setMinimumSize(MINIMUM_CONTENT_WIDTH, MINIMUM_WINDOW_HEIGHT)

        height = clamped_height(window_height, available)
        if height < window_height:
            # The bar takes width from the viewport: give it back, so nothing ends
            # up hidden under the scrollbar.
            width += self.scroll.verticalScrollBar().sizeHint().width()

        # While the widgets are still hidden the measurement is an approximation, so
        # the first pass only records the minimum; the one taken as the window
        # appears is the one that decides the size.
        if not self._initial_size_applied and not initial:
            return
        self._initial_size_applied = True
        if (self.width(), self.height()) != (width, height):
            self.resize(width, height)

    @staticmethod
    def _page_height(page: QWidget, width: int) -> int:
        """Return how tall a page wants to be when it is ``width`` wide."""

        layout = page.layout()
        if layout is not None and layout.hasHeightForWidth():
            return layout.heightForWidth(width)
        return page.sizeHint().height()

    def _chrome_height(self) -> int:
        """Return the height of everything that is not the scrolling pages."""

        outer = self.centralWidget().layout()
        margins = outer.contentsMargins()
        status = self.statusBar()
        return (
            margins.top()
            + margins.bottom()
            + self.banner.sizeHint().height()
            + (status.sizeHint().height() if status is not None else 0)
            + outer.spacing()
        )

    def available_height(self) -> int | None:
        """Return how much vertical room the screen leaves for the window."""

        screen = self.screen()
        if screen is None:  # pragma: no cover - needs no platform plugin at all
            return None
        area = screen.availableGeometry()
        return area.height() if area.height() > 0 else None

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

    def _icon_label(self, text: str, icon: Any, buddy: QWidget | None = None) -> QWidget:
        """Build a field label with a small drawn icon in front of the text.

        The icon is a separate widget rather than a pixmap on the label: a QLabel
        with both a text and a pixmap draws them in the same rectangle, and the
        pixmap lands on top of the words.
        """

        row = QWidget()
        row.setObjectName("fieldLabelRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        picture = QLabel()
        picture.setPixmap(icon.pixmap(14, 14))
        layout.addWidget(picture)
        layout.addWidget(self._field_label(text, buddy), 1)
        return row

    def _build_stream_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Every icon is drawn in the colour of the theme it is drawn for, so the
        # tokens are read once, here, rather than inside each helper.
        tokens = color_tokens(current_theme())

        # The account header first: who this is about, before what to do with it.
        layout.addWidget(self._profile_header(account=False))

        # And then what to do. Everything below is a form, and a form is impossible
        # to start when nobody says which field matters first or how far along you
        # are. It disappears by itself once the directo is prepared.
        self.guide = StepsGuide(GUIDE_STEPS)
        self.guide.dismissed.connect(self.hide_guide)
        layout.addWidget(self.guide)

        # One column, everything stacked: the window is narrow and tall, which is
        # the shape that sits beside OBS and the shape the second page already has.
        layout.addWidget(self._stream_details_card(tokens))
        layout.addWidget(self._connection_card(tokens))

        # Phone-shaped window: three buttons do not fit on one line, so the main
        # action gets the full width — which is also the one thing the user came
        # here to press — and the other two share the line below it.
        self.go_live_btn = QPushButton("Preparar directo")
        self.go_live_btn.setObjectName("primary")
        self.go_live_btn.setIcon(play_icon(16, tokens["primaryText"]))
        self.go_live_btn.setIconSize(QSize(16, 16))
        self.go_live_btn.setToolTip(
            "Pide a Streamlabs que prepare la sesión y devuelve la URL y la clave"
        )
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.clicked.connect(lambda _checked=False: self.start_stream())
        layout.addWidget(self.go_live_btn)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.end_live_btn = QPushButton("Finalizar directo")
        # The one action that throws work away, so it wears the other signature
        # colour instead of looking like every other button.
        self.end_live_btn.setObjectName("danger")
        self.end_live_btn.setIcon(stop_icon(16, tokens["danger"]))
        self.end_live_btn.setIconSize(QSize(16, 16))
        self.end_live_btn.setToolTip(
            "Detén primero la salida de TikTok en OBS y después cierra la sesión de Streamlabs"
        )
        self.end_live_btn.setEnabled(False)
        self.end_live_btn.clicked.connect(lambda _checked=False: self.end_stream())
        actions.addWidget(self.end_live_btn, 1)

        self.save_btn = QPushButton("Guardar ajustes")
        self.save_btn.setIcon(save_icon(16, tokens["text"]))
        self.save_btn.setIconSize(QSize(16, 16))
        self.save_btn.setToolTip(
            "Guarda el título, la categoría y las preferencias (sin secretos)"
        )
        self.save_btn.clicked.connect(lambda _checked=False: self.save_config())
        actions.addWidget(self.save_btn, 1)
        layout.addLayout(actions)

        # The real state of the broadcast, with its own clock. It is separate from
        # the summary because it changes on its own, with the user doing nothing,
        # and a value that moves by itself needs somewhere the eye returns to.
        live_card, live_layout = self._card("Estado del directo")
        live_row = QHBoxLayout()
        live_row.setSpacing(10)
        self.live_state_badge = QLabel("Sin sesión")
        self.live_state_badge.setObjectName("liveState")
        self.live_state_badge.setProperty("state", "neutral")
        live_row.addWidget(self.live_state_badge)
        self.live_elapsed = QLabel("")
        self.live_elapsed.setObjectName("liveElapsed")
        self.live_elapsed.setVisible(False)
        live_row.addWidget(self.live_elapsed)
        live_row.addStretch(1)
        live_layout.addLayout(live_row)
        self.live_hint = QLabel(
            "Cambia solo: mientras la sesión esté abierta, la aplicación vigila el "
            "directo y avisa en cuanto OBS empieza a enviar."
        )
        self.live_hint.setObjectName("muted")
        self.live_hint.setWordWrap(True)
        live_layout.addWidget(self.live_hint)
        layout.addWidget(live_card)

        # What decides whether the stream can be prepared, answered in one line so
        # the account page does not have to be opened to find out.
        self.summary = SummaryStrip(
            (
                ("account", "Cuenta"),
                ("permission", "Puede emitir"),
                ("session", "Sesión"),
            )
        )
        layout.addWidget(self.summary)

        # The link to the account page sits at the bottom, so the space the taller
        # page forces on this one reads as a footer instead of a gap.
        layout.addStretch(1)
        self.account_btn = QPushButton("Cuenta y token")
        self.account_btn.setObjectName("link")
        self.account_btn.setIcon(user_icon(16, tokens["primary"]))
        self.account_btn.setIconSize(QSize(16, 16))
        self.account_btn.setToolTip("Token de Streamlabs, usuario y permiso de emisión")
        self.account_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_btn.clicked.connect(self.show_account_page)
        layout.addWidget(self.account_btn)
        return page

    def _stream_details_card(self, tokens: dict[str, str]) -> QFrame:
        """What the stream is: its title, its category and who it is for."""

        card, card_layout = self._card("Directo")
        self.stream_title = QLineEdit()
        self.stream_title.setToolTip("El título que tendrá el directo en TikTok")
        self.stream_title.textChanged.connect(lambda _text: self._update_controls())
        card_layout.addWidget(self._field_label("&Título del directo", self.stream_title))
        card_layout.addWidget(self.stream_title)

        self.game_category = QLineEdit()
        self.game_category.setToolTip("Escribe para buscar; elige una sugerencia de la lista")
        self.game_category.textChanged.connect(self.handle_game_search)
        card_layout.addWidget(self._field_label("&Categoría", self.game_category))
        card_layout.addWidget(self.game_category)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setMaximumHeight(0)
        self.suggestions_list.hide()
        self.suggestions_list.itemClicked.connect(self.handle_suggestion_selected)
        self._suggestions_animator = HeightAnimator(
            self.suggestions_list,
            natural_height=SUGGESTIONS_HEIGHT,
        )
        # Opening or closing the suggestions changes how tall the page is, and the
        # window is fixed: without measuring again the list ends up squeezed.
        self._suggestions_animator.animation().finished.connect(self._apply_window_size)
        card_layout.addWidget(self.suggestions_list)

        self.mature_checkbox = QCheckBox("Contenido para adultos")
        self.mature_checkbox.setToolTip("Marca la sesión como contenido para adultos")
        self.mature_checkbox.stateChanged.connect(lambda _state: self._update_controls())
        card_layout.addWidget(self.mature_checkbox)
        card_layout.addStretch(1)
        return card

    def _connection_card(self, tokens: dict[str, str]) -> QFrame:
        """Where the stream goes: the server and the key OBS has to be given."""

        card, card_layout = self._card("Conexión")
        self.stream_url = CopyField(placeholder="Aparecerá al preparar el directo")
        self.stream_url.copied.connect(lambda: self.copy_to_clipboard(self.stream_url, False))
        self.copy_url_btn = self.stream_url.copy_button
        card_layout.addWidget(
            self._icon_label(
                "URL del servidor",
                link_icon(14, tokens["muted"]),
                self.stream_url.line_edit,
            )
        )
        card_layout.addWidget(self.stream_url)

        self.stream_key = CopyField(
            sensitive=True,
            revealable=True,
            placeholder="Aparecerá al preparar el directo",
        )
        self.stream_key.copied.connect(lambda: self.copy_to_clipboard(self.stream_key, True))
        self.copy_key_btn = self.stream_key.copy_button
        card_layout.addWidget(
            self._icon_label(
                "Clave de retransmisión",
                key_icon(14, tokens["muted"]),
                self.stream_key.line_edit,
            )
        )
        card_layout.addWidget(self.stream_key)

        note = QLabel("La clave se retira del portapapeles a los 60 segundos.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        card_layout.addWidget(note)
        card_layout.addStretch(1)
        return card

    def _profile_header(self, *, account: bool) -> QFrame:
        """Build the account header, once per page.

        Both pages show it: on the main one it is what the user asks about, and on
        the account one it keeps the page from ending in a stretch of nothing.
        """

        header = QFrame()
        header.setObjectName("card")
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(10)

        card = ProfileCard()
        header_layout.addWidget(card)
        if account:
            self.account_profile_card = card
            header_layout.addLayout(self._picture_row())
            credit = QLabel(
                'Foto: <a href="https://unavatar.io">unavatar.io</a> · '
                'perfil: <a href="https://microlink.io">microlink.io</a>'
            )
            credit.setObjectName("muted")
            credit.setOpenExternalLinks(True)
            header_layout.addWidget(credit)
        else:
            self.profile_card = card
        return header

    def _picture_row(self) -> QHBoxLayout:
        """The buttons that decide where the picture comes from."""

        picture_row = QHBoxLayout()
        picture_row.setSpacing(6)
        self.use_avatar_btn = QPushButton("Usar la de la cuenta")
        self.use_avatar_btn.setToolTip(
            "Descarga la foto del perfil y las cifras públicas de la cuenta"
        )
        self.use_avatar_btn.clicked.connect(lambda _checked=False: self.use_account_avatar())
        picture_row.addWidget(self.use_avatar_btn)

        self.choose_avatar_btn = QPushButton("Elegir imagen…")
        self.choose_avatar_btn.setToolTip(
            "Usa una imagen tuya como foto de la cuenta; se guarda una copia reducida"
        )
        self.choose_avatar_btn.clicked.connect(lambda _checked=False: self.choose_avatar())
        picture_row.addWidget(self.choose_avatar_btn)

        self.remove_avatar_btn = QPushButton("Quitar")
        self.remove_avatar_btn.setToolTip("Vuelve a mostrar la inicial del usuario")
        self.remove_avatar_btn.clicked.connect(lambda _checked=False: self.remove_avatar())
        picture_row.addWidget(self.remove_avatar_btn)
        picture_row.addStretch(1)
        return picture_row

    def _build_account_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        tokens = color_tokens(current_theme())

        layout.addWidget(self._profile_header(account=True))

        token_card, token_layout = self._card("Cuenta de Streamlabs")
        self.token_entry = QLineEdit()
        self.token_entry.setPlaceholderText("Pega aquí el token o cárgalo con los botones…")
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_entry.textChanged.connect(lambda _text: self.handle_token_change())
        self.token_entry.returnPressed.connect(self.refresh_account_info)
        token_layout.addWidget(
            self._icon_label(
                "T&oken de Streamlabs",
                key_icon(14, tokens["muted"]),
                self.token_entry,
            )
        )

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
        self.load_local_btn = QPushButton("Leer del equipo")
        self.load_local_btn.setIcon(refresh_icon(16, tokens["text"]))
        self.load_local_btn.setIconSize(QSize(16, 16))
        self.load_local_btn.setToolTip(
            "Lee el token que Streamlabs Desktop tiene guardado en este equipo"
        )
        self.load_local_btn.clicked.connect(self.load_local_token)
        load_buttons.addWidget(self.load_local_btn)

        self.load_online_btn = QPushButton("Iniciar sesión web")
        self.load_online_btn.setIcon(user_icon(16, tokens["text"]))
        self.load_online_btn.setIconSize(QSize(16, 16))
        self.load_online_btn.setToolTip("Obtiene el token con el inicio de sesión de Streamlabs")
        self.load_online_btn.clicked.connect(self.fetch_online_token)
        load_buttons.addWidget(self.load_online_btn)
        token_layout.addLayout(load_buttons)

        self.refresh_btn = QPushButton("Comprobar la cuenta")
        self.refresh_btn.setIcon(refresh_icon(16, tokens["text"]))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setToolTip(
            "Vuelve a consultar el usuario, el estado y el permiso de emisión"
        )
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_account_info())
        token_layout.addWidget(self.refresh_btn)

        self.save_token_btn = QPushButton("Guardar el token de forma segura")
        self.save_token_btn.setIcon(save_icon(16, tokens["text"]))
        self.save_token_btn.setIconSize(QSize(16, 16))
        self.save_token_btn.setToolTip(
            "Guarda el token validado en el almacén de credenciales del sistema"
        )
        self.save_token_btn.clicked.connect(lambda _checked=False: self.save_token_securely())
        token_layout.addWidget(self.save_token_btn)
        layout.addWidget(token_card)

        account_card, account_layout = self._card("Permiso de emisión")
        live_row = QHBoxLayout()
        live_row.setSpacing(8)
        permission_icon = QLabel()
        permission_icon.setPixmap(shield_icon(14, tokens["muted"]).pixmap(14, 14))
        live_row.addWidget(permission_icon)
        live_row.addWidget(self._field_label("Puede emitir"))
        self.can_go_live = QLabel("—")
        self.can_go_live.setObjectName("badge")
        self.can_go_live.setProperty("state", "neutral")
        live_row.addWidget(self.can_go_live)
        live_row.addStretch(1)
        account_layout.addLayout(live_row)

        self.account_state = QLabel("")
        self.account_state.setObjectName("muted")
        self.account_state.setWordWrap(True)
        account_layout.addWidget(self.account_state)
        layout.addWidget(account_card)

        hint = QLabel(
            "El token se guarda cifrado en el almacén del sistema, nunca en config.json."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        back_row = QHBoxLayout()
        self.back_btn = QPushButton("Volver al directo")
        self.back_btn.setIcon(play_icon(16, tokens["text"]))
        self.back_btn.setIconSize(QSize(16, 16))
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
        menu.addAction("Informar de un problema", self.report_problem)
        menu.addSeparator()
        self.help_btn = menu.addAction("Ayuda", self.show_help)
        self.guide_btn = menu.addAction("Ver la guía de primeros pasos", self.show_guide)
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
