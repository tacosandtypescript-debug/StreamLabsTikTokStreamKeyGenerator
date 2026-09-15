import json

import pytest

from config_store import AppConfig, ConfigError, ConfigStore, read_config_file


def test_save_writes_only_non_secret_preferences(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save(AppConfig(title="Test", game="Fortnite", audience_type="1"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
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
    assert data["schema_version"] == 2
