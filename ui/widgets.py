"""Reusable widgets for the main window.

Each one replaces something that was worse inline:

* :class:`StateBanner` answers "what state am I in?" at a glance instead of
  hiding that answer inside a read-only text field.
* :class:`CopyField` puts the copy button inside the field and confirms in place,
  instead of a full-width button below it plus a modal dialog to dismiss.
* :class:`CollapsibleSection` lets the token panel start folded once it is no
  longer what the user came for, with an animated height instead of a jump.
"""

from __future__ import annotations

import zlib

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import check_icon, copy_icon, eye_icon
from ui.theme import color_tokens, current_theme, state_accent

# Long enough to be noticed, short enough not to feel slow. Anything above
# 250 ms reads as lag in a tool used while a stream is about to start.
ANIMATION_MS = 180
COPIED_FEEDBACK_MS = 1500
# Stable colours for the drawn avatar, chosen to be legible on both themes.
AVATAR_COLORS = (
    "#2563eb",
    "#0f766e",
    "#b45309",
    "#7c3aed",
    "#be123c",
    "#0369a1",
    "#4d7c0f",
    "#a21caf",
)
# The ring around the account picture echoes the two accent colours of the icon.
AVATAR_RING_COLORS = ("#25f4ee", "#fe2c55")
# QWidget's "no maximum" value, used when a section must not clip its content.
UNLIMITED_HEIGHT = 16777215


def _dot_stylesheet(color: str) -> str:
    return f"#bannerDot {{ background-color: {color}; border-radius: 6px; border: none; }}"


class HeightAnimator:
    """Animates the ``maximumHeight`` of a widget.

    Showing or hiding a block then slides instead of moving everything below it
    in a single jump.
    """

    def __init__(
        self,
        widget: QWidget,
        duration: int = ANIMATION_MS,
        natural_height: int | None = None,
    ) -> None:
        self._widget = widget
        self._natural = natural_height if natural_height else widget.sizeHint().height()
        self._animation = QPropertyAnimation(widget, b"maximumHeight", widget)
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Hiding the widget at the end keeps ``isVisible()`` meaningful, and
        # restoring the natural height stops a grown content from being clipped.
        self._animation.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        if self._animation.endValue() == 0:
            self._widget.setVisible(False)
        else:
            self._widget.setMaximumHeight(self.natural_height())

    def animation(self) -> QPropertyAnimation:
        """Return the animation, so a caller can wait for it or inspect it."""

        return self._animation

    def natural_height(self) -> int:
        return max(self._natural, self._widget.sizeHint().height())

    def expand(self) -> None:
        self._widget.setVisible(True)
        self._animate_to(self.natural_height())

    def collapse(self) -> None:
        self._animate_to(0)

    def _animate_to(self, target: int) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._widget.maximumHeight())
        self._animation.setEndValue(target)
        self._animation.start()


class StateBanner(QFrame):
    """A full-width banner: colour dot, headline and one detail line.

    The dot's new colour fades in, so a change of state is noticed without
    anything on screen moving.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # The account, then the state: who this is about, and how it is doing.
        self.avatar = AvatarLabel(26, self)
        self.avatar.set_username("")
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)

        self._dot = QFrame(self)
        self._dot.setObjectName("bannerDot")
        self._dot.setFixedSize(12, 12)
        self._dot_effect = QGraphicsOpacityEffect(self._dot)
        self._dot.setGraphicsEffect(self._dot_effect)
        # Never fully transparent: if the animation does not get to run, the dot
        # must still be visible rather than missing.
        self._dot_effect.setOpacity(1.0)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        self.title_label = QLabel(self)
        self.title_label.setObjectName("bannerTitle")
        self.detail_label = QLabel(self)
        self.detail_label.setObjectName("bannerDetail")
        self.detail_label.setWordWrap(True)
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.detail_label)
        layout.addLayout(text_column, 1)

        self._state = ""
        self._fade = QPropertyAnimation(self._dot_effect, b"opacity", self)
        self._fade.setDuration(ANIMATION_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_state("neutral", "", "")

    def state(self) -> str:
        return self._state

    def fade_animation(self) -> QPropertyAnimation:
        return self._fade

    def dot_color(self) -> str:
        return state_accent(current_theme(), self._state)

    def set_state(self, state: str, headline: str, detail: str = "") -> None:
        """Switch to ``state``: ``neutral``, ``ok``, ``warn``, ``error`` or ``live``.

        Setting the state it already has changes nothing on purpose: the window
        refreshes this on every keystroke, and restarting the fade each time made
        the dot blink while the user typed a title.
        """

        if (state, headline, detail) == (
            self._state,
            self.title_label.text(),
            self.detail_label.text(),
        ):
            return

        self._state = state
        self.title_label.setText(headline)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        # A dynamic property only takes effect once the style is recomputed.
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

        self._dot.setStyleSheet(_dot_stylesheet(self.dot_color()))
        self._fade.stop()
        self._fade.setStartValue(0.35)
        self._fade.setEndValue(1.0)
        self._fade.start()


class AvatarLabel(QWidget):
    """A round account picture, or the username's initial drawn in its place.

    There is no picture to download (Streamlabs does not publish one and TikTok
    needs a browser), so the fallback is the same one every mail or chat client
    uses, and its colour depends only on the username: stable across runs, and
    different accounts are told apart at a glance.
    """

    def __init__(
        self,
        size: int = 28,
        parent: QWidget | None = None,
        *,
        ring: bool = False,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._ring = ring
        self._username = ""
        self._pixmap = None
        self.setFixedSize(size, size)

    def set_username(self, username: str) -> None:
        self._username = (username or "").strip()
        # Nothing to draw before the account is known, and an empty circle looks
        # like a bug; a chosen picture is worth showing on its own.
        self.setVisible(bool(self._username) or self.has_picture())
        self.update()

    def set_picture(self, pixmap) -> None:
        """Use ``pixmap`` as the picture; ``None`` goes back to the initial."""

        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self.setVisible(bool(self._username) or self.has_picture())
        self.update()

    def has_picture(self) -> bool:
        return self._pixmap is not None

    def initial(self) -> str:
        return self._username.lstrip("@")[:1].upper()

    def color(self) -> str:
        """Return the colour of the initial, derived only from the username."""

        if not self._username:
            return color_tokens(current_theme())["muted"]
        # crc32, not hash(): hash() is randomised per process, which would change
        # the colour on every start.
        index = zlib.crc32(self._username.casefold().encode("utf-8")) % len(AVATAR_COLORS)
        return AVATAR_COLORS[index]

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self._size, self._size)
        circle = QPainterPath()
        circle.addEllipse(rect)
        painter.setClipPath(circle)

        if self.has_picture():
            scaled = self._pixmap.scaled(
                self._size,
                self._size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
        else:
            painter.fillPath(circle, QColor(self.color()))
            painter.setPen(QColor("#ffffff"))
            font = QFont(self.font())
            font.setPixelSize(max(int(self._size * 0.45), 9))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.initial() or "?")

        painter.setClipping(False)
        if self._ring:
            # A gradient ring, like the one the network itself draws: the picture
            # is the account's, and the ring says "this is a profile".
            gradient = QConicalGradient(rect.center(), 90)
            gradient.setColorAt(0.0, QColor(AVATAR_RING_COLORS[0]))
            gradient.setColorAt(0.25, QColor(AVATAR_RING_COLORS[1]))
            gradient.setColorAt(0.5, QColor(AVATAR_RING_COLORS[0]))
            gradient.setColorAt(0.75, QColor(AVATAR_RING_COLORS[1]))
            gradient.setColorAt(1.0, QColor(AVATAR_RING_COLORS[0]))
            pen = QPen(QBrush(gradient), 3)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawEllipse(rect.adjusted(1.5, 1.5, -1.5, -1.5))
        else:
            painter.setPen(QPen(QColor(color_tokens(current_theme())["border"]), 1))
            painter.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()


class ProfileCard(QWidget):
    """The account header: picture with a ring, name, numbers and biography.

    Modelled on the network's own profile header, without any of its social
    actions: from this window there is nothing to follow, message or share. Every
    field is optional and hidden when unknown, so nothing is ever invented.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.avatar = AvatarLabel(72, ring=True)
        self.avatar.set_username("")
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(2)
        self.name_label = QLabel(self)
        self.name_label.setObjectName("profileName")
        self.handle_label = QLabel(self)
        self.handle_label.setObjectName("cardSummary")
        self.stats_label = QLabel(self)
        self.stats_label.setObjectName("profileStats")
        self.bio_label = QLabel(self)
        self.bio_label.setObjectName("muted")
        self.bio_label.setWordWrap(True)
        column.addWidget(self.name_label)
        column.addWidget(self.handle_label)
        column.addWidget(self.stats_label)
        column.addSpacing(4)
        column.addWidget(self.bio_label)
        column.addStretch(1)
        layout.addLayout(column, 1)

        self.set_profile("")

    def set_profile(
        self,
        username: str,
        *,
        display_name: str = "",
        followers: str = "",
        likes: str = "",
        bio: str = "",
    ) -> None:
        """Show what is known; anything empty is hidden rather than filled in."""

        username = (username or "").strip().lstrip("@")
        self.avatar.set_username(username)

        handle = f"@{username}" if username else ""
        self.name_label.setText(display_name or handle or "Sin cuenta")
        # Two lines only when there is a name apart from the handle, as the
        # network itself does.
        self.handle_label.setText(handle if display_name else "")
        self.handle_label.setVisible(bool(display_name and handle))

        parts = []
        if likes:
            parts.append(f"{likes} me gusta")
        if followers:
            parts.append(f"{followers} seguidores")
        self.stats_label.setText(" · ".join(parts))
        self.stats_label.setVisible(bool(parts))

        self.bio_label.setText(bio)
        self.bio_label.setVisible(bool(bio))

    def numbers_text(self) -> str:
        return self.stats_label.text()

    def bio_text(self) -> str:
        return self.bio_label.text()


class CopyField(QWidget):
    """A read-only field with the copy button inside it, and optional reveal."""

    copied = Signal()

    def __init__(
        self,
        *,
        sensitive: bool = False,
        revealable: bool = False,
        placeholder: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sensitive = sensitive
        self._tokens = color_tokens(current_theme())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.line_edit = QLineEdit(self)
        self.line_edit.setReadOnly(True)
        self.line_edit.setPlaceholderText(placeholder)
        if sensitive:
            self.line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.line_edit, 1)

        self.reveal_button: QToolButton | None = None
        if revealable:
            self.reveal_button = self._tool_button(
                eye_icon(16, self._tokens["text"]),
                "Mostrar",
            )
            self.reveal_button.clicked.connect(self.toggle_reveal)
            layout.addWidget(self.reveal_button)

        self.copy_button = self._tool_button(
            copy_icon(16, self._tokens["text"]),
            "Copiar al portapapeles",
        )
        self.copy_button.clicked.connect(self._copy)
        layout.addWidget(self.copy_button)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.setInterval(COPIED_FEEDBACK_MS)
        self._feedback_timer.timeout.connect(self._restore_icon)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 - mirrors QLineEdit
        self.line_edit.setText(value)

    def clear(self) -> None:
        self.line_edit.clear()

    def is_revealed(self) -> bool:
        return self.line_edit.echoMode() == QLineEdit.EchoMode.Normal

    def is_confirming(self) -> bool:
        """Return whether the tick is being shown instead of the copy icon."""

        return self._feedback_timer.isActive()

    def toggle_reveal(self) -> None:
        if self.reveal_button is None:
            return
        self.line_edit.setEchoMode(
            QLineEdit.EchoMode.Password if self.is_revealed() else QLineEdit.EchoMode.Normal
        )
        self.reveal_button.setIcon(
            eye_icon(16, self._tokens["text"], open_eye=not self.is_revealed())
        )
        self.reveal_button.setToolTip("Ocultar" if self.is_revealed() else "Mostrar")

    def _tool_button(self, icon, tooltip: str) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _copy(self) -> None:
        if not self.line_edit.text():
            return
        self.copied.emit()
        self.flash_copied()

    def flash_copied(self) -> None:
        """Show the tick for a moment; no dialog to dismiss."""

        self.copy_button.setIcon(check_icon(16, self._tokens["ok"]))
        self.copy_button.setToolTip("Copiado")
        self._feedback_timer.start()

    def _restore_icon(self) -> None:
        self.copy_button.setIcon(copy_icon(16, self._tokens["text"]))
        self.copy_button.setToolTip("Copiar al portapapeles")


class FadingProgressBar(QWidget):
    """An indeterminate bar that fades in and out instead of popping."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(110, 6)
        layout.addWidget(self.bar)

        self._effect = QGraphicsOpacityEffect(self)
        self.bar.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.finished.connect(self._on_finished)
        self._busy = False
        self.hide()

    def is_busy(self) -> bool:
        return self._busy

    def animation(self) -> QPropertyAnimation:
        return self._animation

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        # Called on every control refresh, so the same value must not restart the
        # fade and make the bar flicker.
        if busy == self._busy:
            return
        self._busy = busy
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0 if self._busy else 0.0)
        if self._busy:
            self.show()
        self._animation.start()

    def _on_finished(self) -> None:
        if not self._busy:
            self.hide()
