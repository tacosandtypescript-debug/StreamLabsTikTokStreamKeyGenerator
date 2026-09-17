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


# --------------------------------------------------------------------------- #
#  The avatar service                                                         #
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, content=b"", content_type="image/jpeg", status=200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise avatar_store.requests.HTTPError(f"HTTP {self.status_code}")


def _png_bytes(tmp_path, size=64):
    path = tmp_path / f"origen-{size}.png"
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("#00ff00"))
    assert image.save(str(path), "PNG")
    return path.read_bytes()


def test_the_service_url_demands_a_real_avatar_or_nothing():
    # fallback=false is what turns "no avatar" into a 404 instead of a generic
    # silhouette, which would be shown as if it were the account's photo.
    assert (
        avatar_store.remote_avatar_url("@khetzalgg")
        == "https://unavatar.io/tiktok/khetzalgg?fallback=false"
    )


def test_a_strange_username_is_escaped():
    url = avatar_store.remote_avatar_url("nombre raro/../x")

    assert " " not in url
    assert url.endswith("?fallback=false")
    assert url.count("/") == 4


def test_a_downloaded_picture_is_stored_and_scaled(tmp_path):
    data = _png_bytes(tmp_path, 900)

    stored = avatar_store.save_remote_avatar(
        "khetzalgg",
        http_get=lambda *args, **kwargs: FakeResponse(data),
    )

    assert stored.is_file()
    pixmap = avatar_store.load_avatar()
    assert pixmap is not None
    assert pixmap.width() <= avatar_store.MAX_AVATAR_PIXELS


def test_a_missing_avatar_is_an_error_not_a_generic_image():
    def not_found(*args, **kwargs):
        return FakeResponse(b"", content_type="text/html", status=404)

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar("nadie", http_get=not_found)


def test_a_non_image_answer_is_rejected():
    response = FakeResponse(b"<html>no</html>", content_type="text/html")

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar("khetzalgg", http_get=lambda *a, **k: response)


def test_the_content_type_is_not_trusted(tmp_path):
    # An error page announced as an image must not end up stored as the picture.
    response = FakeResponse(b"<html>no</html>", content_type="image/png")

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.save_remote_avatar("khetzalgg", http_get=lambda *a, **k: response)

    assert avatar_store.has_avatar() is False


def test_an_empty_answer_is_rejected():
    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar("khetzalgg", http_get=lambda *a, **k: FakeResponse(b""))


def test_a_huge_answer_is_rejected():
    huge = b"x" * (avatar_store.MAX_DOWNLOAD_BYTES + 1)

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar(
            "khetzalgg",
            http_get=lambda *a, **k: FakeResponse(huge, "image/png"),
        )


def test_a_network_failure_is_an_error():
    def boom(*args, **kwargs):
        raise avatar_store.requests.ConnectionError("sin red")

    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar("khetzalgg", http_get=boom)


def test_without_a_username_there_is_nothing_to_fetch():
    with pytest.raises(avatar_store.AvatarError):
        avatar_store.fetch_remote_avatar("   ")
