"""Release checking, verified download and installation of updates.

Downloading never runs anything by itself: the asset is verified against the
published ``SHA256SUMS.txt`` and left in the user's download folder. Running an
installer is a separate, explicitly requested step, and it only happens when the
application can actually be replaced while it is running: see
:func:`can_self_install`.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import requests
from packaging import version
from platformdirs import user_downloads_dir

from runtime import is_frozen
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

# The Windows installer published next to the archives.
INSTALLER_PREFIX = "Setup-"
INSTALLER_SUFFIX = ".exe"
# Silent, but with the progress window visible, and without restarting Windows.
# /CLOSEAPPLICATIONS lets Inno's Restart Manager close the running application.
INSTALLER_FLAGS: tuple[str, ...] = (
    "/SILENT",
    "/CLOSEAPPLICATIONS",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
)
INSTALLER_HELPER_NAME = "install-update-{pid}.cmd"
# The application has to release its own files before Inno Setup runs.
INSTALLER_DELAY_SECONDS = 3


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
    *,
    prefer_installer: bool = True,
) -> dict[str, Any] | None:
    """Return the release asset to use on ``system``/``machine``, if any.

    On Windows the installer is preferred when the release publishes one: it
    installs per user, registers an uninstaller and can replace the running
    application, none of which an archive can do.
    """

    hints = PLATFORM_ASSET_HINTS.get(system)
    if hints is None:
        return None

    archives: list[dict[str, Any]] = []
    installers: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if is_installer_asset(asset, system):
            installers.append(asset)
        elif name.endswith(".zip") and any(hint in name for hint in hints):
            archives.append(asset)

    if prefer_installer and installers:
        return installers[0]
    if not archives:
        return None
    if system == "Darwin" and machine:
        wanted = machine.lower()
        for asset in archives:
            if wanted in str(asset["name"]).lower():
                return asset
    return archives[0]


def is_installer_asset(asset: Mapping[str, Any], system: str) -> bool:
    """Return whether ``asset`` is the Windows installer of a release."""

    if system != "Windows":
        return False
    name = asset.get("name")
    return (
        isinstance(name, str)
        and name.startswith(INSTALLER_PREFIX)
        and name.endswith(INSTALLER_SUFFIX)
    )


def can_self_install(system: str, asset: Mapping[str, Any] | None) -> bool:
    """Return whether this build can replace itself with ``asset``.

    Only a compiled Windows build with an installer: a source checkout is
    updated with git, and the archives published for the other platforms cannot
    be swapped while the application is running.
    """

    if system != "Windows" or not asset or not is_frozen():
        return False
    return is_installer_asset(asset, system)


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


def _batch_quote(value: Any) -> str:
    """Quote a path for a batch file.

    Inside double quotes ``&``, ``^`` and spaces are literal, but ``%`` is still
    special, so it is doubled.
    """

    return f'"{str(value).replace("%", "%%")}"'


def installer_helper_script(
    *,
    installer: Path,
    app_executable: Path | None = None,
    log_path: Path | None = None,
    delay_seconds: int = INSTALLER_DELAY_SECONDS,
) -> str:
    """Return the batch script that installs the update once we have exited.

    A running application cannot overwrite its own files, so a detached helper
    waits for the process to disappear, runs the installer and, when the
    installation succeeded, starts the application again. Inno does not relaunch
    it on a silent install, which is why the helper does it.
    """

    flags = list(INSTALLER_FLAGS)
    if log_path is not None:
        flags.append(f"/LOG={_batch_quote(log_path)}")

    lines = [
        "@echo off",
        "rem Update helper written by the application; it can be deleted.",
        f"rem Installer: {installer.name}",
    ]
    if delay_seconds > 0:
        # ``timeout`` refuses to run when it has no console to read from, which is
        # exactly the case for a detached helper, so ``ping`` is the sleep.
        lines.append(f"ping -n {int(delay_seconds) + 1} 127.0.0.1 >NUL")
    lines.append(" ".join([_batch_quote(installer), *flags]))
    if app_executable is not None:
        lines.extend(
            [
                "if not errorlevel 1 (",
                f"  start \"\" {_batch_quote(app_executable)}",
                ")",
            ]
        )
    return "\n".join(lines) + "\n"


def write_installer_helper(
    directory: Path,
    *,
    installer: Path,
    app_executable: Path | None = None,
    log_path: Path | None = None,
    delay_seconds: int = INSTALLER_DELAY_SECONDS,
) -> Path:
    """Write the update helper inside ``directory`` and return its path.

    The script is written as UTF-8. A path containing characters outside the
    console code page would need a different encoding, which is why the window
    always tells the user where the installer is so it can be run by hand.
    """

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    helper = directory / INSTALLER_HELPER_NAME.format(pid=os.getpid())
    helper.write_text(
        installer_helper_script(
            installer=Path(installer),
            app_executable=None if app_executable is None else Path(app_executable),
            log_path=None if log_path is None else Path(log_path),
            delay_seconds=delay_seconds,
        ),
        encoding="utf-8",
    )
    return helper


def launch_detached(helper: Path) -> None:
    """Run ``helper`` outside this process, so it survives our exit."""

    helper = Path(helper)
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(["cmd.exe", "/c", str(helper)], close_fds=True, creationflags=flags)
        return
    subprocess.Popen(["/bin/sh", str(helper)], close_fds=True, start_new_session=True)
