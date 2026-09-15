import json

import pytest

from config_store import (
    CURRENT_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    ActiveSession,
    AppConfig,
    ConfigError,
    ConfigStore,
    read_config_file,
)


def test_save_writes_only_non_secret_preferences(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save(AppConfig(title="Test", game="Fortnite", audience_type="1"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["title"] == "Test"
    assert "token" not in data


def test_legacy_token_is_detected_without_being_saved(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "token": "abc123",
                "title": "Old title",
                "game": "Fortnite",
                "audience_type": "0",
            }
        ),
        encoding="utf-8",
    )

    result = read_config_file(path)

    assert result.legacy_token == "abc123"
    assert result.had_legacy_token is True
    assert result.config.title == "Old title"


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / "config.json"
    original = "{not-json"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigError):
        read_config_file(path)

    assert path.read_text(encoding="utf-8") == original


def test_boolean_audience_value_is_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"audience_type": True}), encoding="utf-8")

    with pytest.raises(ConfigError):
        read_config_file(path)


def test_migrate_legacy_file_removes_token(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"token": "secret", "title": "Title"}), encoding="utf-8")

    ConfigStore.migrate_legacy_file(path, AppConfig(title="Title"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in data
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION


def test_file_without_schema_version_is_treated_as_legacy(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"title": "Old"}), encoding="utf-8")

    result = read_config_file(path)

    assert result.source_schema_version == LEGACY_SCHEMA_VERSION
    assert result.needs_upgrade is True
    assert result.config.title == "Old"
    assert result.config.schema_version == CURRENT_SCHEMA_VERSION


def test_current_schema_file_needs_no_upgrade(tmp_path):
    path = tmp_path / "config.json"
    ConfigStore(path).save(AppConfig(title="Test"))

    result = read_config_file(path)

    assert result.source_schema_version == CURRENT_SCHEMA_VERSION
    assert result.needs_upgrade is False


def test_newer_schema_is_refused_instead_of_overwritten(tmp_path):
    path = tmp_path / "config.json"
    original = json.dumps({"schema_version": CURRENT_SCHEMA_VERSION + 1, "title": "Future"})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigError):
        read_config_file(path)

    assert path.read_text(encoding="utf-8") == original


def test_non_integer_schema_version_is_refused(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": "two"}), encoding="utf-8")

    with pytest.raises(ConfigError):
        read_config_file(path)


def test_declined_migration_preference_round_trips(tmp_path):
    path = tmp_path / "config.json"
    ConfigStore(path).save(AppConfig(legacy_migration_declined=True))

    assert read_config_file(path).config.legacy_migration_declined is True


def test_active_session_round_trips(tmp_path):
    path = tmp_path / "config.json"
    session = ActiveSession("session-1", "My title", "2026-01-01T00:00:00+00:00")
    ConfigStore(path).save(AppConfig(active_session=session))

    assert read_config_file(path).config.active_session == session


def test_saved_session_holds_no_secret(tmp_path):
    path = tmp_path / "config.json"
    ConfigStore(path).save(
        AppConfig(active_session=ActiveSession("session-1", "Title", "2026-01-01"))
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in data
    assert data["active_session"] == {
        "session_id": "session-1",
        "title": "Title",
        "started_at": "2026-01-01",
    }


def test_missing_session_is_none(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"title": "x"}), encoding="utf-8")

    assert read_config_file(path).config.active_session is None


def test_session_without_id_is_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_session": {"title": "x"}}), encoding="utf-8")

    with pytest.raises(ConfigError):
        read_config_file(path)


def test_session_with_wrong_types_is_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"active_session": {"session_id": "s", "title": 5}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        read_config_file(path)
