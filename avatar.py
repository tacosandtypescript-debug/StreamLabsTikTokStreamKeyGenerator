"""The account picture.

Streamlabs does not publish an avatar for the authorised account and TikTok only
serves its own to a browser, so the picture comes from `unavatar.io`, a free
service that aggregates profile pictures from many networks. Its anonymous tier
allows 25 lookups a day per address with a 24 hour cache, which is why the image
is stored locally and only fetched when the account changes, never on every
start. The user can also choose a file of their own instead, and then no service
is asked at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from platformdirs import user_config_dir

from config_store import APP_AUTHOR, APP_NAME

LOGGER = logging.getLogger(__name__)

AVATAR_FILENAME = "avatar.png"
# The window shows it at 28 or 48 pixels; storing a phone photo would otherwise
# put megabytes in the configuration folder.
MAX_AVATAR_PIXELS = 256
SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# The aggregation service, and the provider name it uses for TikTok.
AVATAR_SERVICE_URL = "https://unavatar.io"
AVATAR_PROVIDER = "tiktok"
AVATAR_SERVICE_NAME = "unavatar.io"
# A profile picture is a few hundred kilobytes; anything much bigger is not one.
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
DOWNLOAD_TIMEOUT = (10.0, 30.0)


class AvatarError(RuntimeError):
    """Raised when a picture cannot be obtained, read or stored."""


def avatar_directory() -> Path:
    """Return the folder the account picture is kept in."""

    return Path(user_config_dir(APP_NAME, APP_AUTHOR))


def avatar_path() -> Path:
    """Return the full path of the stored account picture."""

    return avatar_directory() / AVATAR_FILENAME


def has_avatar() -> bool:
    """Return whether there is a picture to show."""

    return avatar_path().is_file()


def remote_avatar_url(username: str, provider: str = AVATAR_PROVIDER) -> str:
    """Return the service URL that resolves an account's picture.

    ``fallback=false`` is deliberate: without it the service answers with a
    generic silhouette when it finds nothing, and the window would show a
    stranger's placeholder as if it were the account's photo.
    """

    clean = (username or "").strip().lstrip("@")
    return f"{AVATAR_SERVICE_URL}/{provider}/{quote(clean, safe='')}?fallback=false"


def fetch_remote_avatar(
    username: str,
    *,
    http_get: Callable[..., Any] = requests.get,
    timeout: tuple[float, float] = DOWNLOAD_TIMEOUT,
) -> bytes:
    """Download an account's picture and return its bytes."""

    if not (username or "").strip().lstrip("@"):
        raise AvatarError("No hay ninguna cuenta de la que traer la foto.")

    url = remote_avatar_url(username)
    try:
        response = http_get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AvatarError("No se pudo descargar la foto de la cuenta.") from exc

    headers = getattr(response, "headers", None) or {}
    content_type = str(headers.get("Content-Type", "")) if hasattr(headers, "get") else ""
    if not content_type.startswith("image/"):
        raise AvatarError("El servicio no devolvió una imagen.")

    data = response.content or b""
    if not data:
        raise AvatarError("La imagen llegó vacía.")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise AvatarError("La imagen de la cuenta es demasiado grande.")
    return data


def _store_image(image: Any) -> Path:
    """Scale an image down if needed and write it as the account picture."""

    from PySide6.QtCore import Qt

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


def save_avatar(source: Path) -> Path:
    """Scale the file ``source`` down and store it as the account picture."""

    from PySide6.QtGui import QImage

    source = Path(source)
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise AvatarError("El archivo no es una imagen compatible (PNG, JPG, WebP o BMP).")

    image = QImage(str(source))
    if image.isNull():
        raise AvatarError("No se pudo leer la imagen.")
    return _store_image(image)


def save_avatar_data(data: bytes) -> Path:
    """Store already downloaded image bytes as the account picture."""

    from PySide6.QtGui import QImage

    image = QImage.fromData(data)
    if image.isNull():
        # A wrong content type, an error page or a truncated download all land
        # here instead of being stored as a broken picture.
        raise AvatarError("Lo que llegó no es una imagen válida.")
    return _store_image(image)


def save_remote_avatar(
    username: str,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> Path:
    """Download an account's picture from the service and store it."""

    return save_avatar_data(fetch_remote_avatar(username, http_get=http_get))


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
    """Forget the stored picture, so the initial is drawn again."""

    try:
        avatar_path().unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("The stored account picture could not be removed")
