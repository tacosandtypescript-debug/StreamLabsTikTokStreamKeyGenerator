"""Diagnostic report export for bug reports.

A non-technical user can save a small ZIP that describes the environment and
carries the application log with every secret removed, so it can be attached to
a GitHub issue without leaking an OAuth token or a stream key.

The module stays deliberately small and free of GUI, network and keyring
imports: it must remain importable and cheap from a Nuitka ``--standalone``
build, where the source tree is not present at runtime.
"""

from __future__ import annotations

import os
import platform
import re
import sys
import zipfile
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from config_store import APP_NAME, ConfigError, ConfigStore
from logging_setup import log_directory, log_file_path
from runtime import is_frozen, program_path
from Updater import default_download_dir
from version import __version__

DIAGNOSTICS_PREFIX = "diagnostico"
REPORT_ENTRY_NAME = "diagnostico.txt"
REDACTED = "«oculto»"

REPOSITORY_URL = (
    "https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
)
ISSUE_URL = f"{REPOSITORY_URL}/issues/new"
# GitHub takes long links, but a body nobody scrolls through helps nobody.
MAX_ISSUE_BODY = 1400
# What gets published in a public issue. The paths the full report carries are left
# out on purpose: they contain the user's name.
PUBLIC_SUMMARY_FIELDS = (
    "Versión de la aplicación",
    "Sistema operativo",
    "Arquitectura",
    "Empaquetado",
    "Almacén seguro del token",
)

# Values shorter than this are not treated as secrets. Configuration-like
# fragments ("0", "true", a two-letter game id) would otherwise be replaced
# everywhere in the log and destroy exactly what makes the report useful.
MIN_SECRET_LENGTH = 6

# Only the end of a log is interesting in an issue. The value is used both as a
# character budget and as a byte budget: UTF-8 never produces more characters
# than bytes, so the redacted tail can never exceed this many characters.
MAX_LOG_TAIL_CHARS = 200_000

# RotatingFileHandler numbers its backups consecutively; collecting a handful
# keeps the ZIP small while still covering the recent history.
MAX_ROTATED_LOGS = 5

_SECRET_KEY_NAMES = (
    "access_token",
    "refresh_token",
    "code_verifier",
    "stream_key",
    "api_key",
    "password",
    "secret",
    "token",
)
_KEY_PATTERN = "|".join(_SECRET_KEY_NAMES)
# Characters that end an unquoted value inside a log line.
_UNQUOTED_STOP_CHARS = r"""\s"',;&)\]}>"""

# "Authorization: <value>" up to the end of the line or up to the closing
# quote. The key name and the surrounding punctuation survive, and a trailing
# "Bearer" is redacted together with the value, so the log stays readable.
_AUTHORIZATION_RE = re.compile(
    r"(?i)(?P<key>\bauthorization\b[\"']?\s*[:=]\s*[\"']?)(?P<value>[^\r\n\"']*)"
)

# A bare "Bearer <value>" that the rule above did not already consume.
_BEARER_RE = re.compile(r"(?i)(?P<key>\bbearer\s+)(?P<value>[^\s\"',;]+)")

# Quoted values: token="...", "stream_key": "...", 'password': '...'
_QUOTED_VALUE_RE = re.compile(
    rf"""
    (?i)
    (?P<key>(?<![A-Za-z0-9_])["']?(?:{_KEY_PATTERN})["']?)
    (?P<separator>\s*[:=]\s*)
    (?P<quote>["'])(?P<value>[^"'\r\n]*)(?P=quote)
    """,
    re.VERBOSE,
)

# Unquoted values: token=..., stream_key: ...
_UNQUOTED_VALUE_RE = re.compile(
    rf"""
    (?i)
    (?P<key>(?<![A-Za-z0-9_])["']?(?:{_KEY_PATTERN})["']?)
    (?P<separator>\s*[:=]\s*)
    (?P<value>[^{_UNQUOTED_STOP_CHARS}]+)
    """,
    re.VERBOSE,
)


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """Return ``text`` with every known secret replaced by ``REDACTED``.

    There is intentionally no rule that redacts "long looking" strings: doing
    so would wipe session identifiers, URLs, file names and checksums, which is
    precisely the information a maintainer needs to diagnose a report. Only the
    exact values handed over in ``secrets`` and the small set of patterns that
    describe a secret written into a log line are removed.
    """

    if not text:
        return text

    cleaned = text
    for secret in secrets:
        if not isinstance(secret, str):
            continue
        needle = secret.strip()
        # Short values are configuration-like fragments, not secrets.
        if len(needle) < MIN_SECRET_LENGTH:
            continue
        cleaned = cleaned.replace(needle, REDACTED)

    cleaned = _AUTHORIZATION_RE.sub(_redact_value, cleaned)
    cleaned = _BEARER_RE.sub(_redact_value, cleaned)
    cleaned = _QUOTED_VALUE_RE.sub(_redact_value, cleaned)
    cleaned = _UNQUOTED_VALUE_RE.sub(_redact_value, cleaned)
    return cleaned


def _redact_value(match: re.Match[str]) -> str:
    """Replace the value of a matched assignment, keeping the key readable."""

    groups = match.groupdict()
    prefix = (groups.get("key") or "") + (groups.get("separator") or "")
    quote = groups.get("quote") or ""
    return f"{prefix}{quote}{REDACTED}{quote}"


def system_summary() -> dict[str, str]:
    """Return short, Spanish-labelled facts about the running application.

    The mapping never contains the OAuth token, the stream key or the session
    identifier: only environment facts that help triage a report.
    """

    return {
        "Versión de la aplicación": __version__,
        "Sistema operativo": f"{platform.system()} {platform.release()}".strip(),
        "Arquitectura": platform.machine() or "desconocida",
        "Versión de Python": platform.python_version(),
        "Empaquetado": "sí" if is_frozen() else "no",
        "Ruta del programa": str(program_path()),
        "Carpeta de registros": str(log_directory()),
        "Archivo de registro": str(log_file_path()),
        "Almacén seguro del token": _secure_store_status(),
        "Instalación": _install_location(),
        "Sesión de Streamlabs guardada": _saved_session_status(),
    }


def issue_url(summary: dict[str, str] | None = None, *, problem: str = "") -> str:
    """Return a link that opens a new issue with the facts already written in.

    Reporting has to cost one click: the application talks to internal Streamlabs
    endpoints, so the day they change something it stops working for everybody and the
    author would otherwise never hear about it.

    Only the facts that do not identify the machine are published. The paths are left
    out on purpose — they carry the user's name — and the full diagnostics stay in the
    file the user attaches if they want to. The token, the stream key and the session
    identifier are never part of any of it.
    """

    facts = system_summary() if summary is None else summary
    lines = [
        "### Qué pasa",
        "",
        problem.strip() or "(cuéntalo aquí: qué hacías y qué salió mal)",
        "",
        "### Datos",
        "",
    ]
    lines.extend(
        f"- **{name}**: {facts[name]}" for name in PUBLIC_SUMMARY_FIELDS if name in facts
    )
    lines += [
        "",
        "### Informe completo",
        "",
        "Si puedes, adjunta el informe: **Más → Guardar informe de diagnóstico** lo deja",
        "en el escritorio, ya sin el token ni la clave.",
    ]
    body = "\n".join(lines)[:MAX_ISSUE_BODY]
    version = facts.get("Versión de la aplicación", "")
    query = urlencode(
        {
            "title": f"[Problema] {version}".strip(),
            "body": body,
        }
    )
    return f"{ISSUE_URL}?{query}"


def _secure_store_status() -> str:
    """Report whether the OS-backed token store looks usable.
    so this module keeps keyring out of its own import graph while still
    reporting the verdict of the component that actually owns the token.
    """

    try:
        from secure_store import SecureTokenStore
    except ImportError:  # pragma: no cover - defensive, the module ships with the app
        return "no se pudo comprobar"
    try:
        available = SecureTokenStore().is_available()
    except Exception:
        return "no se pudo comprobar"
    return "disponible" if available else "no disponible"


def _saved_session_status() -> str:
    """Report whether a Streamlabs session was left open, never its identifier."""

    try:
        result = ConfigStore().load()
    except (ConfigError, OSError):
        return "no se pudo comprobar"
    return "sí" if result.config.active_session is not None else "no"


def _install_location() -> str:
    """Return the platform-specific folder the application is installed in."""

    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return str(Path(local_app_data) / "Programs" / APP_NAME)
    elif sys.platform == "darwin":
        return f"/Applications/{APP_NAME}.app"
    else:
        data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return str(Path(data_home) / APP_NAME)

    # Last resort: wherever the running executable or script happens to live.
    return str(program_path().parent)


def build_report(
    destination: Path,
    *,
    summary: Mapping[str, str],
    log_path: Path | None,
    secret_values: Iterable[str] = (),
) -> Path:
    """Write a diagnostic ZIP at ``destination`` and return its final path.

    A missing or unreadable log is described in Spanish inside the report; a
    genuine OS failure while writing the archive propagates, because the caller
    shows a message to the user. The ZIP is built next to its final location
    with a ``.part`` suffix and moved into place with ``os.replace``, so a
    failure never leaves a half-written report behind.
    """

    destination = Path(destination)
    secrets = tuple(secret_values)
    temporary = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(REPORT_ENTRY_NAME, _report_text(summary, log_path, secrets))
            for rotated in _rotated_log_paths(log_path):
                archive.writestr(rotated.name, _log_entry_text(rotated, secrets))
        os.replace(temporary, destination)
    except BaseException:
        _discard(temporary)
        raise
    return destination


def _report_text(
    summary: Mapping[str, str],
    log_path: Path | None,
    secrets: tuple[str, ...],
) -> str:
    """Build the readable Spanish report stored as the first ZIP entry."""

    parts = ["Informe de diagnóstico de la aplicación", ""]
    for key, value in summary.items():
        parts.append(f"{key}: {value}")
    parts.extend(
        [
            "",
            "---",
            "",
            "Últimas líneas del registro de la aplicación:",
            "",
            _log_entry_text(log_path, secrets),
        ]
    )
    return scrub("\n".join(parts) + "\n", secrets)


def _log_entry_text(log_path: Path | None, secrets: tuple[str, ...]) -> str:
    """Return the redacted tail of one log file, never raising for it."""

    if log_path is None:
        return "No se encontró el archivo de registro."
    path = Path(log_path)
    try:
        if not path.is_file():
            return f"No se encontró el archivo de registro: {path}"
        return scrub(_read_tail(path, MAX_LOG_TAIL_CHARS), secrets)
    except OSError as exc:
        return f"No se pudo leer el archivo de registro {path}: {exc}"


def _read_tail(path: Path, limit: int) -> str:
    """Return at most ``limit`` characters from the end of ``path``."""

    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit:
            handle.seek(size - limit)
            data = handle.read(limit)
            # The cut may land in the middle of a line (and of a secret), so the
            # first partial line is dropped.
            newline = data.find(b"\n")
            if newline != -1:
                data = data[newline + 1 :]
        else:
            data = handle.read()
    return data.decode("utf-8", errors="replace")


def _rotated_log_paths(log_path: Path | None) -> list[Path]:
    """Return the rotated logs that sit next to ``log_path``, in order."""

    if log_path is None:
        return []
    path = Path(log_path)
    rotated: list[Path] = []
    for index in range(1, MAX_ROTATED_LOGS + 1):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.is_file():
            # Backups are numbered consecutively: the first gap ends the list.
            break
        rotated.append(candidate)
    return rotated


def _discard(path: Path) -> None:
    """Delete a failed temporary file; cleanup is best effort only."""

    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort cleanup
        pass


def default_report_path(now: datetime | None = None) -> Path:
    """Return the file name proposed to the user for the ZIP export."""

    moment = now if now is not None else datetime.now()
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    return default_download_dir() / f"{DIAGNOSTICS_PREFIX}-{stamp}.zip"
