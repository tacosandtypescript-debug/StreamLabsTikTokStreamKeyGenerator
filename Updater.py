"""Release checking and verified download of updates.

The download path never executes anything: it fetches the release asset,
verifies it against the published ``SHA256SUMS.txt`` and leaves it in the
user's download folder for them to run when they decide to.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import requests
from packaging import version
from platformdirs import user_downloads_dir

from version import __version__

# A source checkout reports a development version, which has nothing
# meaningful to compare against.
DEV_VERSION_SUFFIX = "-dev"
CHECKSUMS_ASSET_NAME = "SHA256SUMS.txt"
DOWNLOAD_CHUNK_BYTES = 256 * 1024

# Filename fragments that identify the package built for each platform.
PLATFORM_ASSET_HINTS: dict[str, tuple[str, ...]] = {
    "Windows": ("-win-",),
    "Darwin": ("-macos-",),
    "Linux": ("-linux-",),
}


class DownloadError(RuntimeError):
    """Raised when a release asset cannot be downloaded or verified."""


class DownloadCancelled(DownloadError):
    """Raised when the user cancels a download."""


class ChecksumMismatchError(DownloadError):
    """Raised when a downloaded file does not match its published checksum."""


class VersionChecker:
    # This must be the repository that publishes the releases downloaded by the
    # users of this application, not the upstream project it derives from.
    REPO = "tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
    API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

    @classmethod
    def check_update(cls, http_get: Any = requests.get) -> dict[str, Any] | None:
        current = __version__.lstrip("v")
        if current.endswith(DEV_VERSION_SUFFIX):
            # Never nag the user from a development build.
            return None

        try:
            response = http_get(
                cls.API_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": cls.REPO},
                timeout=(5, 10),
            )
            response.raise_for_status()
            release = response.json()
            if not isinstance(release, dict):
                return None

            latest = release.get("tag_name")
            release_url = release.get("html_url")
            if not isinstance(latest, str) or not isinstance(release_url, str):
                return None
            latest = latest.lstrip("v")
            if version.parse(latest) <= version.parse(current):
                return None

            assets, checksums_url = _collect_assets(release.get("assets"))
            return {
                "current": __version__,
                "latest": latest,
                "url": release_url,
                "notes": str(release.get("body") or ""),
                "assets": assets,
                "checksums_url": checksums_url,
            }
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ):
            return None


def _collect_assets(raw_assets: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Normalise the release asset list and locate the checksums file."""

    assets: list[dict[str, Any]] = []
    checksums_url: str | None = None
    if not isinstance(raw_assets, list):
        return assets, checksums_url

    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        size = item.get("size")
        assets.append({"name": name, "url": url, "size": size if isinstance(size, int) else 0})
        if name == CHECKSUMS_ASSET_NAME:
            checksums_url = url
    return assets, checksums_url


def select_asset(
    assets: Iterable[dict[str, Any]],
    system: str,
    machine: str = "",
) -> dict[str, Any] | None:
    """Return the release asset built for ``system``/``machine``, if any."""

    hints = PLATFORM_ASSET_HINTS.get(system)
    if hints is None:
        return None

    candidates: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not name.endswith(".zip"):
            continue
        if any(hint in name for hint in hints):
            candidates.append(asset)

    if not candidates:
        return None
    if system == "Darwin" and machine:
        wanted = machine.lower()
        for asset in candidates:
            if wanted in str(asset["name"]).lower():
                return asset
    return candidates[0]


def parse_checksum(checksums_text: str, filename: str) -> str | None:
    """Return the SHA-256 recorded for ``filename`` in a ``sha256sum`` file."""

    for line in checksums_text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest = parts[0].strip().lower()
        recorded = parts[1].strip().lstrip("*")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            continue
        if recorded == filename or recorded.endswith("/" + filename):
            return digest
    return None


def default_download_dir() -> Path:
    """Return the folder where downloaded releases are stored."""

    return Path(user_downloads_dir())


def fetch_checksum(
    checksums_url: str,
    filename: str,
    *,
    http_get: Callable[..., Any] = requests.get,
    timeout: tuple[float, float] = (10.0, 30.0),
) -> str | None:
    """Fetch a ``SHA256SUMS.txt`` asset and return the digest for ``filename``."""

    try:
        response = http_get(checksums_url, timeout=timeout)
        response.raise_for_status()
        text = response.text
    except requests.RequestException as exc:
        raise DownloadError("No se pudo consultar el checksum de la release.") from exc

    if not isinstance(text, str):
        return None
    return parse_checksum(text, filename)


def download_asset(
    url: str,
    destination: Path,
    *,
    http_get: Callable[..., Any] = requests.get,
    expected_sha256: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: tuple[float, float] = (10.0, 120.0),
) -> Path:
    """Download a release asset and verify it before making it visible.

    The bytes are written to a ``.part`` file first and only moved into place
    once the digest matches, so an interrupted or tampered download never looks
    like a usable package.
    """

    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    written = 0

    try:
        response = http_get(url, stream=True, timeout=timeout)
        try:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled("Descarga cancelada por el usuario.")
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, total)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except DownloadError:
        _discard(partial)
        raise
    except requests.RequestException as exc:
        _discard(partial)
        raise DownloadError("No se pudo descargar la actualización.") from exc
    except OSError as exc:
        _discard(partial)
        raise DownloadError(f"No se pudo escribir la descarga en {partial.parent}.") from exc

    actual = digest.hexdigest()
    if expected_sha256 is not None and actual != expected_sha256.strip().lower():
        _discard(partial)
        raise ChecksumMismatchError(
            "El archivo descargado no coincide con el checksum publicado; se ha descartado."
        )

    try:
        os.replace(partial, destination)
    except OSError as exc:
        _discard(partial)
        raise DownloadError(f"No se pudo guardar la descarga en {destination}.") from exc
    return destination


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort cleanup
        pass
