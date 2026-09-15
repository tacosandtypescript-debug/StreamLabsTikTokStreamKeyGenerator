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
class AppConfig:
    schema_version: int = CURRENT_SCHEMA_VERSION
    title: str = ""
    game: str = ""
    audience_type: str = "0"
    suppress_donation_reminder: bool = False
    legacy_migration_declined: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "game": self.game,
            "audience_type": self.audience_type,
            "suppress_donation_reminder": self.suppress_donation_reminder,
            "legacy_migration_declined": self.legacy_migration_declined,
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


def _parse_config(data: Any) -> ConfigLoadResult:
    if not isinstance(data, dict):
        raise ConfigError("La configuración debe ser un objeto JSON.")

    source_schema = _schema_version(data)

    audience_type = data.get("audience_type", "0")
    if isinstance(audience_type, bool) or audience_type not in {"0", "1", 0, 1}:
        raise ConfigError("El campo audience_type no es válido.")

    suppress = _bool_value(data, "suppress_donation_reminder", False)
    declined = _bool_value(data, "legacy_migration_declined", False)

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
