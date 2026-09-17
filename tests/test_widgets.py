"""The reusable widgets: banner, copy field and progress bar."""

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ui.theme import BANNER_STATES, state_accent
from ui.widgets import (
    ANIMATION_MS,
    COPIED_FEEDBACK_MS,
    AvatarLabel,
    ContentScrollArea,
    ContentStack,
    CopyField,
    FadingProgressBar,
    HeightAnimator,
    StateBanner,
)


def test_the_banner_shows_a_headline_and_a_detail(qtbot):
    banner = StateBanner()
    qtbot.addWidget(banner)

    banner.set_state("ok", "Listo", "todo bien")

    assert banner.state() == "ok"
    assert banner.title_label.text() == "Listo"
    assert banner.detail_label.text() == "todo bien"
    assert banner.property("state") == "ok"
    assert banner.detail_label.isHidden() is False


def test_the_banner_hides_an_empty_detail(qtbot):
    banner = StateBanner()
    qtbot.addWidget(banner)

    banner.set_state("neutral", "Sin token")

    assert banner.detail_label.isHidden() is True


def test_every_banner_state_has_its_own_accent_colour():
    accents = {state: state_accent("light", state) for state in BANNER_STATES}

    assert len(set(accents.values())) == len(BANNER_STATES)
    assert all(state_accent("dark", state) for state in BANNER_STATES)


def test_an_unknown_state_falls_back_to_the_neutral_accent():
    assert state_accent("light", "inventado") == state_accent("light", "neutral")


def test_the_banner_fades_its_dot_on_every_change(qtbot):
    banner = StateBanner()
    qtbot.addWidget(banner)

    banner.set_state("ok", "Listo")

    assert banner.fade_animation().duration() == ANIMATION_MS
    assert banner.fade_animation().state() == QAbstractAnimation.State.Running


def test_setting_the_state_it_already_has_changes_nothing(qtbot):
    # The window refreshes the banner on every keystroke; restarting the fade
    # there made the dot blink while a title was being typed.
    banner = StateBanner()
    qtbot.addWidget(banner)
    banner.set_state("ok", "Listo", "detalle")
    qtbot.waitUntil(
        lambda: banner.fade_animation().state() == QAbstractAnimation.State.Stopped,
        timeout=2000,
    )

    banner.set_state("ok", "Listo", "detalle")

    assert banner.fade_animation().state() == QAbstractAnimation.State.Stopped


def test_the_banner_still_reacts_to_a_real_change(qtbot):
    banner = StateBanner()
    qtbot.addWidget(banner)
    banner.set_state("ok", "Listo", "detalle")
    qtbot.waitUntil(
        lambda: banner.fade_animation().state() == QAbstractAnimation.State.Stopped,
        timeout=2000,
    )

    banner.set_state("error", "Sin permiso", "detalle")

    assert banner.state() == "error"
    assert banner.fade_animation().state() == QAbstractAnimation.State.Running


def test_the_copy_field_reports_a_copy_and_confirms_in_place(qtbot):
    field = CopyField()
    qtbot.addWidget(field)
    field.setText("hola")
    copies = []
    field.copied.connect(lambda: copies.append(True))

    field.copy_button.click()

    assert copies == [True]
    assert field.is_confirming() is True
    assert field.copy_button.toolTip() == "Copiado"


def test_the_copy_confirmation_goes_away_on_its_own(qtbot):
    field = CopyField()
    qtbot.addWidget(field)
    field.setText("hola")

    field.copy_button.click()
    qtbot.waitUntil(lambda: not field.is_confirming(), timeout=COPIED_FEEDBACK_MS + 2000)

    assert field.copy_button.toolTip() == "Copiar al portapapeles"


def test_an_empty_copy_field_does_not_claim_to_have_copied(qtbot):
    field = CopyField()
    qtbot.addWidget(field)
    copies = []
    field.copied.connect(lambda: copies.append(True))

    field.copy_button.click()

    assert copies == []
    assert field.is_confirming() is False


def test_a_sensitive_field_hides_its_text_and_can_reveal_it(qtbot):
    field = CopyField(sensitive=True, revealable=True)
    qtbot.addWidget(field)

    assert field.is_revealed() is False

    field.reveal_button.click()
    assert field.is_revealed() is True

    field.reveal_button.click()
    assert field.is_revealed() is False


def test_a_plain_field_has_no_reveal_button(qtbot):
    field = CopyField()
    qtbot.addWidget(field)

    assert field.reveal_button is None


def test_the_copy_field_keeps_the_line_edit_interface(qtbot):
    field = CopyField()
    qtbot.addWidget(field)

    field.setText("algo")
    assert field.text() == "algo"

    field.clear()
    assert field.text() == ""
    assert field.is_confirming() is False


def test_the_avatar_draws_the_initial_of_the_username(qtbot):
    label = AvatarLabel()
    qtbot.addWidget(label)

    label.set_username("@khetzalgg")

    assert label.initial() == "K"
    assert label.has_picture() is False


def test_the_avatar_colour_depends_only_on_the_username(qtbot):
    first = AvatarLabel()
    second = AvatarLabel()
    qtbot.addWidget(first)
    qtbot.addWidget(second)

    first.set_username("khetzalgg")
    second.set_username("Khetzalgg")

    assert first.color() == second.color()


def test_different_accounts_get_different_colours(qtbot):
    colours = set()
    for name in ("uno", "dos", "tres", "cuatro", "cinco"):
        label = AvatarLabel()
        qtbot.addWidget(label)
        label.set_username(name)
        colours.add(label.color())

    assert len(colours) > 1


def test_the_avatar_is_hidden_until_there_is_an_account(qtbot):
    label = AvatarLabel()
    qtbot.addWidget(label)

    label.set_username("")
    assert label.isHidden() is True

    label.set_username("khetzalgg")
    assert label.isHidden() is False


def test_a_picture_replaces_the_initial(qtbot):
    label = AvatarLabel()
    qtbot.addWidget(label)
    label.set_username("khetzalgg")
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#00ff00"))

    label.set_picture(pixmap)
    assert label.has_picture() is True

    label.set_picture(None)
    assert label.has_picture() is False


def test_an_unusable_pixmap_is_ignored(qtbot):
    label = AvatarLabel()
    qtbot.addWidget(label)
    label.set_username("khetzalgg")

    label.set_picture(QPixmap())

    assert label.has_picture() is False


def test_the_avatar_paints_with_and_without_a_picture(qtbot):
    label = AvatarLabel(28)
    qtbot.addWidget(label)
    label.set_username("khetzalgg")

    assert label.grab().width() == 28

    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("#123456"))
    label.set_picture(pixmap)

    assert label.grab().width() == 28


def test_the_animator_can_be_told_the_natural_height(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)

    animator = HeightAnimator(widget, natural_height=120)

    assert animator.natural_height() == 120


def test_the_progress_bar_fades_in_and_out(qtbot):
    bar = FadingProgressBar()
    qtbot.addWidget(bar)

    assert bar.is_busy() is False
    assert bar.isVisible() is False

    bar.set_busy(True)
    assert bar.is_busy() is True
    assert bar.isVisible() is True

    bar.set_busy(False)
    assert bar.is_busy() is False
    qtbot.waitUntil(lambda: bar.isVisible() is False, timeout=2000)


def test_repeating_the_busy_state_does_not_restart_the_fade(qtbot):
    bar = FadingProgressBar()
    qtbot.addWidget(bar)
    bar.set_busy(True)
    qtbot.waitUntil(
        lambda: bar.animation().state() == QAbstractAnimation.State.Stopped,
        timeout=2000,
    )

    bar.set_busy(True)

    assert bar.animation().state() == QAbstractAnimation.State.Stopped


def test_the_stack_accepts_the_height_the_window_worked_out(qtbot):
    # Qt's own hint is measured at the width the widget would like to have, which is
    # narrower here, so it exaggerates and would make the pages scroll for nothing.
    stack = ContentStack()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())

    stack.set_content_height(495)

    assert stack.minimumSizeHint().height() == 495
    assert stack.content_height() == 495


def test_the_stack_keeps_its_own_hint_until_something_is_measured(qtbot):
    stack = ContentStack()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())

    assert stack.content_height() == 0
    assert stack.minimumSizeHint() == stack.sizeHint()


def test_the_stack_ignores_a_nonsense_height(qtbot):
    stack = ContentStack()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())

    stack.set_content_height(-40)

    assert stack.content_height() == 0


def test_the_scroll_area_reports_the_size_of_its_content(qtbot):
    body = QWidget()
    qtbot.addWidget(body)
    layout = QVBoxLayout(body)
    child = QWidget()
    child.setFixedSize(300, 520)
    layout.addWidget(child)
    area = ContentScrollArea()
    qtbot.addWidget(area)

    area.setWidget(body)

    # Exactly what the content asks for, plus its own frame: that is what the window
    # measures, and the frame is part of the widget.
    frame = area.frameWidth() * 2
    assert area.sizeHint().height() == body.sizeHint().height() + frame
    assert area.minimumSizeHint().height() == body.minimumSizeHint().height() + frame
    assert area.sizeHint().height() >= 520


def test_a_scroll_area_whose_content_has_no_size_answers_for_itself(qtbot):
    body = QWidget()
    qtbot.addWidget(body)
    area = ContentScrollArea()
    qtbot.addWidget(area)

    area.setWidget(body)

    assert area.sizeHint().width() > 0
    assert area.minimumSizeHint().width() > 0
