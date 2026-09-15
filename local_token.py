"""Read the Streamlabs Desktop API token from its local storage.

This is the "Cargar desde el PC" path. It deliberately lives outside the GUI module
so it can be tested without importing Qt.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

TOKEN_PATTERN = re.compile(rb'"apiToken"\s*:\s*"([a-f0-9]{16,})"', re.IGNORECASE)
MAX_TOKEN_FILE_BYTES = 25 * 1024 * 1024


class LocalTokenUnsupportedError(RuntimeError):
    """Raised when Streamlabs local data is not available on this OS."""


class LocalTokenNotFoundError(RuntimeError):
    """Raised when the local storage exists but holds no usable token."""


def local_storage_dir() -> Path:
    """Return the Streamlabs Desktop local-storage directory for this system.

    Raises:
        LocalTokenUnsupportedError: on any system other than Windows or macOS.
    """

    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise LocalTokenUnsupportedError("No se encontró la carpeta AppData de Windows.")
        return Path(appdata) / "slobs-client" / "Local Storage" / "leveldb"
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "slobs-client"
            / "Local Storage"
            / "leveldb"
        )
    raise LocalTokenUnsupportedError(
        f"La importación local solo está disponible en Windows y macOS, no en {system}. "
        "Usa «Iniciar sesión web» en Linux."
    )


def find_local_token() -> str | None:
    """Return the newest ``apiToken`` found in Streamlabs local storage.

    Returns ``None`` when the directory does not exist or no token is present.
    Raises:
        LocalTokenUnsupportedError: on an unsupported system or without AppData.
    """

    base = local_storage_dir()
    if not base.is_dir():
        return None

    try:
        files = [
            file
            for pattern in ("*.log", "*.ldb")
            for file in base.glob(pattern)
            if file.is_file()
        ]
    except OSError as exc:
        raise LocalTokenNotFoundError(
            f"No se pudo leer la carpeta de datos de Streamlabs: {base}"
        ) from exc

    files.sort(key=lambda file: file.stat().st_mtime, reverse=True)
    for file in files:
        try:
            if file.stat().st_size > MAX_TOKEN_FILE_BYTES:
                continue
            content = file.read_bytes()
        except OSError:
            continue
        for match in reversed(TOKEN_PATTERN.findall(content)):
            token = match.decode("ascii", errors="ignore").strip()
            if token:
                return token
    return None


def local_token_hint() -> str:
    """Return a message explaining why the local token was not found."""

    try:
        base = local_storage_dir()
    except LocalTokenUnsupportedError as exc:
        return str(exc)
    if not base.is_dir():
        return (
            "No se encontró la carpeta de datos de Streamlabs Desktop. "
            "Instálalo e inicia sesión con tu cuenta de TikTok, o usa «Iniciar sesión web»."
        )
    return (
        "La carpeta de datos de Streamlabs existe, pero no contiene un token "
        "reconocible. Puede que hayas cerrado la sesión ahí o que su formato haya "
        "cambiado; usa «Iniciar sesión web»."
    )
