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
from typing import Sequence

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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import check_icon, copy_icon, eye_icon
from ui.text import strip_unsupported_emoji
from ui.theme import color_tokens, current_theme, state_accent

# Long enough to be noticed, short enough not to feel slow. Anything above
# 250 ms reads as lag in a tool used while a stream is about to start.
ANIMATION_MS = 180
COPIED_FEEDBACK_MS = 1500
# Stable colours for the drawn avatar, chosen to be legible on both themes and to
# sit alongside the two signature colours without clashing with them.
AVATAR_COLORS = (
    "#0f8b8d",
    "#7c3aed",
    "#fe2c55",
    "#2563eb",
    "#b45309",
    "#0369a1",
    "#4d7c0f",
    "#a21caf",
)
# The ring around the account picture, and the offset glow drawn behind it, are the
# two signature colours of the icon: the cyan and the rose, one nudged each way.
AVATAR_RING_COLORS = ("#25f4ee", "#fe2c55")
# How far each glow copy is offset, as a fraction of the picture's size.
AVATAR_GLOW_OFFSET = 0.055
# The ring thickness, in pixels, for a picture of any size.
AVATAR_RING_WIDTH = 3
# Room left around the profile picture so the offset glow behind it is not clipped
# by the layout that holds it.
AVATAR_GLOW_MARGIN = 6
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

        if self._ring:
            self._paint_glow(painter, rect)

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
            pen = QPen(QBrush(gradient), AVATAR_RING_WIDTH)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            inset = AVATAR_RING_WIDTH / 2
            painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
        else:
            painter.setPen(QPen(QColor(color_tokens(current_theme())["border"]), 1))
            painter.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()

    @staticmethod
    def _paint_glow(painter: QPainter, rect: QRectF) -> None:
        """Draw the offset cyan-and-rose copy that sits behind the picture.

        It is the same ring twice, each copy nudged the other way, which is what
        gives the profile picture the coloured edge the network's own has. Drawn
        behind the image and clipped to nothing, so it reads as a halo rather than
        as two extra circles.
        """

        offset = rect.width() * AVATAR_GLOW_OFFSET
        radius = rect.width() / 2
        for color, dx, dy in (
            (AVATAR_RING_COLORS[0], -offset, 0.0),
            (AVATAR_RING_COLORS[1], offset, 0.0),
        ):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(
                QRectF(
                    rect.center().x() - radius + dx,
                    rect.center().y() - radius + dy,
                    rect.width(),
                    rect.height(),
                )
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)


class ContentStack(QStackedWidget):
    """A stack that accepts being shorter than its content's own minimum hint.

    Qt derives a layout's minimum from its widgets' hints, and those are measured at
    the width the widget would *like* to have. At the width the window actually has,
    the wrapped labels need fewer lines and therefore less height. Trusting the hint
    would make the pages scroll when they fit perfectly well, so the stack is told
    the height the window computed for it instead.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content_height = 0

    def set_content_height(self, height: int) -> None:
        """Record how tall the pages really need to be at the width they have."""

        self._content_height = max(int(height), 0)
        self.updateGeometry()

    def content_height(self) -> int:
        return self._content_height

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if self._content_height:
            return QSize(hint.width(), self._content_height)
        return hint


class ContentScrollArea(QScrollArea):
    """A scroll area that reports the size of what it holds.

    Qt's own ``sizeHint`` for a resizable scroll area is a small default, so a
    window measured through it would come out far too small. This one answers with
    the content's size, which is what the window has to be exactly as big as; and
    when the screen has no room for that, the area scrolls because the content keeps
    its own minimum height.
    """

    def sizeHint(self) -> QSize:
        widget = self.widget()
        if widget is None:  # pragma: no cover - the widget is set at build time
            return super().sizeHint()
        hint = widget.sizeHint()
        if not hint.isValid():  # a widget with no layout has no size of its own
            return super().sizeHint()
        frame = self.frameWidth() * 2
        return QSize(hint.width() + frame, hint.height() + frame)

    def minimumSizeHint(self) -> QSize:
        """The content's own minimum, so nothing is ever squeezed inside."""

        widget = self.widget()
        if widget is None:  # pragma: no cover - the widget is set at build time
            return super().minimumSizeHint()
        hint = widget.minimumSizeHint()
        if not hint.isValid():  # a widget with no layout has no minimum of its own
            return super().minimumSizeHint()
        frame = self.frameWidth() * 2
        return QSize(hint.width() + frame, hint.height() + frame)


class ProfileCard(QWidget):
    """The account header: picture with a ring, name, numbers and biography.

    Modelled on the network's own profile header, without any of its social
    actions: from this window there is nothing to follow, message or share. Every
    field is optional and hidden when unknown, so nothing is ever invented.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(AVATAR_GLOW_MARGIN, AVATAR_GLOW_MARGIN,
                                  AVATAR_GLOW_MARGIN, AVATAR_GLOW_MARGIN)
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

        # The numbers as the profile itself lays them out: a large figure with a
        # small caption underneath, one column each, divided by hairlines. Built
        # once and hidden as a block, because the three have to appear together.
        self.stats_row = QWidget(self)
        stats_layout = QHBoxLayout(self.stats_row)
        stats_layout.setContentsMargins(0, 6, 0, 6)
        stats_layout.setSpacing(16)
        self.stat_values: dict[str, QLabel] = {}
        # Both widgets of a column, so an unknown figure can hide its caption too.
        self.stat_fields: dict[str, tuple[QLabel, QLabel]] = {}
        for index, (key, caption) in enumerate(
            (("following", "Siguiendo"), ("followers", "Seguidores"), ("likes", "Me gusta"))
        ):
            if index:
                divider = QFrame(self.stats_row)
                divider.setObjectName("statDivider")
                divider.setFixedWidth(1)
                stats_layout.addWidget(divider, 0)
            stats_layout.addLayout(self._build_stat(key, caption), 0)
        stats_layout.addStretch(1)

        # Kept for the single-line form, used when only one number is known and a
        # three-column row would be two thirds empty.
        self.stats_label = QLabel(self)
        self.stats_label.setObjectName("profileStats")

        self.bio_label = QLabel(self)
        self.bio_label.setObjectName("muted")
        self.bio_label.setWordWrap(True)
        column.addWidget(self.name_label)
        column.addWidget(self.handle_label)
        column.addWidget(self.stats_row)
        column.addWidget(self.stats_label)
        column.addSpacing(4)
        column.addWidget(self.bio_label)
        column.addStretch(1)
        layout.addLayout(column, 1)

        self.set_profile("")

    def _build_stat(self, key: str, caption: str) -> QVBoxLayout:
        """One figure with its caption underneath, as the profile draws them."""

        column = QVBoxLayout()
        column.setSpacing(0)
        value = QLabel(self.stats_row)
        value.setObjectName("statValue")
        label = QLabel(caption, self.stats_row)
        label.setObjectName("statLabel")
        column.addWidget(value)
        column.addWidget(label)
        self.stat_values[key] = value
        self.stat_fields[key] = (value, label)
        return column

    def set_profile(
        self,
        username: str,
        *,
        display_name: str = "",
        followers: str = "",
        likes: str = "",
        bio: str = "",
        following: str = "",
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

        numbers = {"following": following, "followers": followers, "likes": likes}
        for key, (value, caption) in self.stat_fields.items():
            # The caption keeps its own text: it is the label of the column, not a
            # copy of the figure above it.
            value.setText(numbers[key])
            value.setVisible(bool(numbers[key]))
            caption.setVisible(bool(numbers[key]))
        # Three columns when there is more than one number; a single figure reads
        # better on its own line than marooned in the first of three columns.
        use_row = len([value for value in numbers.values() if value]) > 1
        self.stats_row.setVisible(use_row)

        parts = []
        if likes:
            parts.append(f"{likes} me gusta")
        if followers:
            parts.append(f"{followers} seguidores")
        self.stats_label.setText(" · ".join(parts))
        self.stats_label.setVisible(bool(parts) and not use_row)

        # Emoji come from TikTok inside the biography; if this machine cannot draw
        # them, they are dropped here rather than shown as empty boxes.
        self.bio_label.setText(strip_unsupported_emoji(bio))
        self.bio_label.setVisible(bool(bio))

    def numbers_text(self) -> str:
        """Return the figures, in the layout they are currently drawn in.

        The three-column row reads following, followers, likes — the order the
        profile itself uses. The single-line fallback keeps the older order, so the
        one number that is usually known (the likes) still comes first there.

        Which layout is in use is decided from the *content*, not from
        ``isVisible()``: a widget inside a window that was never shown reports that
        it is not visible either, and this has to answer the same way regardless.
        """

        filled = {key: label.text() for key, label in self.stat_values.items()}
        if len([value for value in filled.values() if value]) > 1:
            parts = [
                f"{filled[key]} {caption}"
                for key, caption in (
                    ("following", "siguiendo"),
                    ("followers", "seguidores"),
                    ("likes", "me gusta"),
                )
                if filled[key]
            ]
            if parts:
                return " · ".join(parts)
        return self.stats_label.text()

    def bio_text(self) -> str:
        return self.bio_label.text()


class StepsGuide(QFrame):
    """What to do, showing only the step you are on until you ask for the rest.

    The application used to open on a screen full of fields — token, permission,
    category, OBS — with nothing saying which of them mattered first or how far along
    the user was. Someone opening it for the first time could not tell whether they
    were missing a step or doing it wrong.

    It shows one line by default. The full list is five steps tall and the window is
    exactly as tall as its content, so spelling out the steps already done cost more
    height than it was worth — the current step is the only one that has to be on
    screen, and the rest are one click away.

    Every step is answered by state the window already holds, so the guide cannot
    claim a step is done when it is not: the tick comes from the same values that
    enable the buttons.
    """

    dismissed = Signal()

    def __init__(self, steps: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guide")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._steps = list(steps)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(5)

        # The one line that is always visible: the step in hand.
        heading_row = QHBoxLayout()
        heading_row.setSpacing(8)
        self.mark_label = QLabel("●", self)
        self.mark_label.setObjectName("guideMark")
        self.mark_label.setFixedWidth(18)
        self.mark_label.setProperty("state", "current")
        heading_row.addWidget(self.mark_label, 0, Qt.AlignmentFlag.AlignTop)
        self.current_label = QLabel(self)
        self.current_label.setObjectName("guideStep")
        self.current_label.setWordWrap(True)
        self.current_label.setProperty("state", "current")
        heading_row.addWidget(self.current_label, 1)
        layout.addLayout(heading_row)

        self.detail_label = QLabel(self)
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        # The whole list, folded away until it is asked for.
        self.list_body = QWidget(self)
        list_layout = QVBoxLayout(self.list_body)
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(3)
        self._rows: list[tuple[QLabel, QLabel]] = []
        for text, _detail in self._steps:
            row = QHBoxLayout()
            row.setSpacing(8)
            mark = QLabel(self.list_body)
            mark.setObjectName("guideMark")
            mark.setFixedWidth(18)
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel(text, self.list_body)
            label.setObjectName("guideStep")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            list_layout.addLayout(row)
            self._rows.append((mark, label))
        self.list_body.setVisible(False)
        layout.addWidget(self.list_body)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.toggle_btn = QPushButton("Ver los 5 pasos", self)
        self.toggle_btn.setObjectName("link")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_details)
        buttons.addWidget(self.toggle_btn)
        buttons.addStretch(1)
        self.hide_btn = QPushButton("Ocultar", self)
        self.hide_btn.setObjectName("link")
        self.hide_btn.setToolTip("Oculta esta guía; puedes volver a verla desde «Más»")
        self.hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_btn.clicked.connect(self.dismissed.emit)
        buttons.addWidget(self.hide_btn)
        layout.addLayout(buttons)

    def toggle_details(self) -> None:
        """Show or hide the whole list."""

        showing = not self.list_body.isVisible()
        self.list_body.setVisible(showing)
        self.toggle_btn.setText("Ocultar los pasos" if showing else "Ver los 5 pasos")

    def details_shown(self) -> bool:
        return self.list_body.isVisible()

    def set_progress(self, index: int) -> None:
        """Show the step in hand, and mark the whole list behind it.

        ``index`` equal to the number of steps means everything is done. Passing
        ``-1`` means "cannot tell yet", which is not the same as unfinished: an
        account that has not answered yet must not be called a missing step.
        """

        if 0 <= index < len(self._steps):
            text, detail = self._steps[index]
            self.current_label.setText(text)
            self.detail_label.setText(detail)
            self.detail_label.setVisible(bool(detail))
        elif index >= len(self._steps):
            self.current_label.setText("Todo listo: pega la URL y la clave en OBS")
            self.detail_label.setText("El estado cambiará solo en cuanto OBS empiece a enviar.")
            self.detail_label.setVisible(True)
        else:
            self.current_label.setText("Primeros pasos")
            self.detail_label.setVisible(False)

        headline_state = "done" if index >= len(self._steps) else "current"
        for widget in (self.mark_label, self.current_label):
            if widget.property("state") != headline_state:
                widget.setProperty("state", headline_state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

        for position, (mark, label) in enumerate(self._rows):
            done = index >= 0 and position < index
            current = index >= 0 and position == index
            mark.setText("✓" if done else ("●" if current else "○"))
            state = "done" if done else ("current" if current else "pending")
            for widget in (mark, label):
                if widget.property("state") != state:
                    widget.setProperty("state", state)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

    def step_state(self, position: int) -> str:
        """Return the state drawn for one step, for tests and for callers."""

        return str(self._rows[position][0].property("state"))


class SummaryStrip(QFrame):
    """One row of label-and-value pairs, divided by hairlines.

    The main page is the one used with a stream about to start, so the three
    things that decide whether it can start — which account, whether it may
    broadcast and whether a session is already open — are answered here, in one
    line, instead of being spread over the banner, the account page and the
    button label.
    """

    def __init__(self, fields: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("summaryStrip")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        self._keys: dict[str, QLabel] = {}
        self._values: dict[str, QLabel] = {}

        for index, (key, label) in enumerate(fields):
            if index:
                divider = QFrame(self)
                divider.setObjectName("summaryDivider")
                divider.setFixedWidth(1)
                layout.addWidget(divider, 0)
            layout.addLayout(self._build_item(key, label), 1)

    def _build_item(self, key: str, label: str) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(1)
        caption = QLabel(label, self)
        caption.setObjectName("summaryKey")
        value = QLabel("—", self)
        value.setObjectName("summaryValue")
        value.setProperty("state", "neutral")
        column.addWidget(caption)
        column.addWidget(value)
        self._keys[key] = caption
        self._values[key] = value
        return column

    def set_value(self, key: str, value: str, state: str = "neutral") -> None:
        """Show ``value`` for ``key``, tinted by ``state``.

        The tint is a dynamic property, so the style has to be recomputed for it
        to take effect; only the value label carries it, never the whole strip.
        """

        label = self._values.get(key)
        if label is None:
            return
        label.setText(value or "—")
        if label.property("state") != state:
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

    def value(self, key: str) -> str:
        """Return what is currently shown for ``key``, for tests and callers."""

        label = self._values.get(key)
        return label.text() if label is not None else ""


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
