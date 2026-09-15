"""Versioned, non-secret application configuration."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "StreamLabsTikTokStreamKeyGenerator"
# Deliberately kept identical to the upstream author so that existing
# installations keep both their configuration directory and their keyring
# entry. Changing it would silently orphan the stored token.
APP_AUTHOR = "Loukious"
CONFIG_FILENAME = "config.json"

LEGACY_SCHEMA_VERSION = 1
CURRENT_SCHEMA_VERSION = 2


class ConfigError(RuntimeError):
    """Raised when configuration cannot be read or written safely."""


@dataclass(frozen=True)
class ActiveSession:
    """A Streamlabs session that may still be open on the server side.

    It holds no secret: only the session id Streamlabs returned, the title it
    was started with and an ISO-8601 timestamp. Keeping it lets the application
    offer to close a session left behind by an earlier run.
    """

    session_id: str
    title: str = ""
    started_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class AppConfig:
    schema_version: int = CURRENT_SCHEMA_VERSION
    title: str = ""
    game: str = ""
    audience_type: str = "0"
    suppress_donation_reminder: bool = False
    legacy_migration_declined: bool = False
    active_session: ActiveSession | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "game": self.game,
            "audience_type": self.audience_type,
            "suppress_donation_reminder": self.suppress_donation_reminder,
            "legacy_migration_declined": self.legacy_migration_declined,
            "active_session": self.active_session.to_dict() if self.active_session else None,
        }


@dataclass(frozen=True)
class ConfigLoadResult:
    config: AppConfig
    legacy_token: str | None = None
    had_legacy_token: bool = False
    source_schema_version: int = CURRENT_SCHEMA_VERSION
    needs_upgrade: bool = False


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME, APP_AUTHOR)) / CONFIG_FILENAME


def _string_value(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"El campo de configuración '{key}' no es texto.")
    return value


def _bool_value(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"El campo de configuración '{key}' no es booleano.")
    return value


def _schema_version(data: dict[str, Any]) -> int:
    """Return the schema version of a configuration mapping.

    Files written before schema versioning existed have no ``schema_version``
    key at all and are therefore treated as version 1.
    """

    raw = data.get("schema_version", LEGACY_SCHEMA_VERSION)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ConfigError("El campo schema_version no es un número entero.")
    if raw > CURRENT_SCHEMA_VERSION:
        raise ConfigError(
            "La configuración procede de una versión más reciente de la aplicación."
        )
    if raw < LEGACY_SCHEMA_VERSION:
        raise ConfigError("La versión del esquema de configuración no está soportada.")
    return raw


def _active_session(data: dict[str, Any]) -> ActiveSession | None:
    raw = data.get("active_session")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("El campo active_session no es un objeto JSON.")

    session_id = raw.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ConfigError("La sesión guardada no tiene un identificador válido.")

    title = raw.get("title", "")
    started_at = raw.get("started_at", "")
    if not isinstance(title, str) or not isinstance(started_at, str):
        raise ConfigError("Los datos de la sesión guardada no son válidos.")

    return ActiveSession(
        session_id=session_id.strip(),
        title=title,
        started_at=started_at,
    )


def _parse_config(data: Any) -> ConfigLoadResult:
    if not isinstance(data, dict):
        raise ConfigError("La configuración debe ser un objeto JSON.")

    source_schema = _schema_version(data)

    audience_type = data.get("audience_type", "0")
    if isinstance(audience_type, bool) or audience_type not in {"0", "1", 0, 1}:
        raise ConfigError("El campo audience_type no es válido.")

    suppress = _bool_value(data, "suppress_donation_reminder", False)
    declined = _bool_value(data, "legacy_migration_declined", False)
    session = _active_session(data)

    legacy_token = data.get("token")
    if legacy_token is not None and not isinstance(legacy_token, str):
        raise ConfigError("El token legado no es texto.")

    # The in-memory configuration is always at the current schema version;
    # ``needs_upgrade`` tells the caller to persist the upgraded file.
    config = AppConfig(
        title=_string_value(data, "title"),
        game=_string_value(data, "game"),
        audience_type=str(audience_type),
        suppress_donation_reminder=suppress,
        legacy_migration_declined=declined,
        active_session=session,
    )
    return ConfigLoadResult(
        config=config,
        legacy_token=legacy_token.strip() if legacy_token and legacy_token.strip() else None,
        had_legacy_token=bool(legacy_token and legacy_token.strip()),
        source_schema_version=source_schema,
        needs_upgrade=source_schema != CURRENT_SCHEMA_VERSION,
    )


def read_config_file(path: Path) -> ConfigLoadResult:
    """Read one JSON file without overwriting it on errors."""

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return ConfigLoadResult(config=AppConfig())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"No se pudo leer la configuración: {path}") from exc

    return _parse_config(data)


class ConfigStore:
    """Atomic storage for non-sensitive preferences."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()

    def load(self) -> ConfigLoadResult:
        return read_config_file(self.path)

    def save(self, config: AppConfig) -> None:
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n"
        self._atomic_write(self.path, payload)

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        temporary_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temporary_path = Path(temp_file.name)
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ConfigError(f"No se pudo guardar la configuración: {path}") from exc

    @staticmethod
    def migrate_legacy_file(path: Path, config: AppConfig) -> None:
        """Replace a legacy file with non-secret preferences after consent."""

        ConfigStore._atomic_write(
            path,
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
