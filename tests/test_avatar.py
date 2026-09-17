"""The account picture: storing it, scaling it down and forgetting it."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage

import avatar as avatar_store


@pytest.fixture(autouse=True)
def qt_app(qapp):
    """QPixmap and the image plugins need a QGuiApplication."""

    return qapp


@pytest.fixture(autouse=True)
def isolated_directory(tmp_path, monkeypatch):
    """Never touch the real configuration folder."""

    monkeypatch.setattr(avatar_store, "avatar_directory", lambda: tmp_path)
    return tmp_path


def _write_image(path, width=64, height=64, colour="#ff0000"):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    assert image.save(str(path), "PNG")
    return path


def test_without_a_picture_there_is_nothing_to_load():
    assert avatar_store.has_avatar() is False
    assert avatar_store.load_avatar() is None


def test_a_chosen_picture_is_stored_and_loaded(tmp_path):
    stored = avatar_store.save_avatar(_write_image(tmp_path / "foto.png"))

    assert stored == avatar_store.avatar_path()
    assert avatar_store.has_avatar() is True
    pixmap = avatar_store.load_avatar()
    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (64, 64)


def test_a_huge_picture_is_scaled_down(tmp_path):
    avatar_store.save_avatar(_write_image(tmp_path / "grande.png", 1200, 800))

    pixmap = avatar_store.load_avatar()

    assert pixmap.width() <= avatar_store.MAX_AVATAR_PIXELS
    assert pixmap.height() <= avatar_store.MAX_AVATAR_PIXELS


def test_a_small_picture_is_kept_as_it_is(tmp_path):
    avatar_store.save_avatar(_write_image(tmp_path / "pequena.png", 40, 40))

    assert avatar_store.load_avatar().width() == 40


def test_a_file_that_is_not_an_image_is_rejected(tmp_path):
    source = tmp_path / "notas.txt"
    source.write_text("no soy una imagen", encoding="utf-8")

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.save_avatar(source)


def test_a_file_that_cannot_be_decoded_is_rejected(tmp_path):
    source = tmp_path / "rota.png"
    source.write_bytes(b"esto no es un PNG")

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.save_avatar(source)


def test_the_picture_can_be_forgotten(tmp_path):
    avatar_store.save_avatar(_write_image(tmp_path / "foto.png"))

    avatar_store.remove_avatar()

    assert avatar_store.has_avatar() is False
    assert avatar_store.load_avatar() is None


def test_forgetting_a_picture_that_does_not_exist_is_harmless():
    avatar_store.remove_avatar()
    avatar_store.remove_avatar()

    assert avatar_store.has_avatar() is False


def test_an_unreadable_stored_picture_is_not_a_crash(tmp_path):
    (tmp_path / avatar_store.AVATAR_FILENAME).write_bytes(b"basura")

    assert avatar_store.has_avatar() is True
    assert avatar_store.load_avatar() is None


def test_the_picture_lives_next_to_the_configuration():
    # Documented on purpose: it is a user file, not a secret, and it is not in
    # the repository nor in the log folder.
    assert avatar_store.avatar_path().name == avatar_store.AVATAR_FILENAME
    assert avatar_store.avatar_path().parent == avatar_store.avatar_directory()
