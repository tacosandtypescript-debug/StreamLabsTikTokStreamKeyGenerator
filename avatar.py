"""The account picture, which has to be the user's own.

Streamlabs does not return an avatar for the authorised account, and TikTok does
not expose one without executing its JavaScript, so there is nothing to download.
Two honest options remain, and both live here: the window draws the username's
initial when there is no picture, and the user can pick a file of their own, which
is copied next to the configuration and scaled down.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from config_store import APP_AUTHOR, APP_NAME

LOGGER = logging.getLogger(__name__)

AVATAR_FILENAME = "avatar.png"
# The window shows it at 28 or 48 pixels; storing a phone photo would otherwise
# put megabytes in the configuration folder.
MAX_AVATAR_PIXELS = 256
SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


class AvatarError(RuntimeError):
    """Raised when the chosen file cannot be used as an account picture."""


def avatar_directory() -> Path:
    """Return the folder the account picture is kept in."""

    return Path(user_config_dir(APP_NAME, APP_AUTHOR))


def avatar_path() -> Path:
    """Return the full path of the stored account picture."""

    return avatar_directory() / AVATAR_FILENAME


def has_avatar() -> bool:
    """Return whether the user has chosen a picture."""

    return avatar_path().is_file()


def save_avatar(source: Path) -> Path:
    """Scale ``source`` down and store it as the account picture."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    source = Path(source)
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AvatarError("El archivo no es una imagen compatible (PNG, JPG, WebP o BMP).")

    image = QImage(str(source))
    if image.isNull():
        raise AvatarError("No se pudo leer la imagen.")
    if image.width() > MAX_AVATAR_PIXELS or image.height() > MAX_AVATAR_PIXELS:
        image = image.scaled(
            MAX_AVATAR_PIXELS,
            MAX_AVATAR_PIXELS,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    destination = avatar_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(destination), "PNG"):
            raise AvatarError("No se pudo guardar la imagen.")
    except OSError as exc:
        raise AvatarError(f"No se pudo guardar la imagen en {destination}.") from exc

    LOGGER.info("Account picture stored (%sx%s)", image.width(), image.height())
    return destination


def load_avatar() -> Any:
    """Return the stored picture as a ``QPixmap``, or ``None`` when there is none."""

    from PySide6.QtGui import QPixmap

    path = avatar_path()
    if not path.is_file():
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        LOGGER.warning("The stored account picture could not be read")
        return None
    return pixmap


def remove_avatar() -> None:
    """Forget the chosen picture, so the initial is drawn again."""

    try:
        avatar_path().unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("The stored account picture could not be removed")
