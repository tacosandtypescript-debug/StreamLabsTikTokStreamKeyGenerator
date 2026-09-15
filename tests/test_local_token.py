import os
import time

import pytest

import local_token
from local_token import (
    LocalTokenUnsupportedError,
    find_local_token,
    local_storage_dir,
    local_token_hint,
)


def _make_storage(tmp_path):
    base = tmp_path / "slobs-client" / "Local Storage" / "leveldb"
    base.mkdir(parents=True)
    return base


def _as_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(local_token.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))


def test_reads_the_token_from_the_windows_location(tmp_path, monkeypatch):
    base = _make_storage(tmp_path)
    token = "a" * 32
    (base / "000001.log").write_bytes(f'{{"apiToken":"{token}"}}'.encode("ascii"))
    _as_windows(monkeypatch, tmp_path)

    assert find_local_token() == token


def test_prefers_the_most_recently_modified_file(tmp_path, monkeypatch):
    base = _make_storage(tmp_path)
    older = base / "000001.log"
    newer = base / "000002.log"
    older.write_bytes(b'"apiToken":"' + b"1" * 32 + b'"')
    newer.write_bytes(b'"apiToken":"' + b"2" * 32 + b'"')
    stamp = time.time() - 120
    os.utime(older, (stamp, stamp))
    _as_windows(monkeypatch, tmp_path)

    assert find_local_token() == "2" * 32


def test_returns_none_when_the_directory_is_missing(tmp_path, monkeypatch):
    _as_windows(monkeypatch, tmp_path)

    assert find_local_token() is None


def test_returns_none_when_no_token_is_present(tmp_path, monkeypatch):
    base = _make_storage(tmp_path)
    (base / "000001.log").write_bytes(b"nothing to see here")
    _as_windows(monkeypatch, tmp_path)

    assert find_local_token() is None


def test_ignores_files_above_the_size_limit(tmp_path, monkeypatch):
    base = _make_storage(tmp_path)
    oversized = base / "000001.log"
    with oversized.open("wb") as handle:
        handle.write(b"\0" * (local_token.MAX_TOKEN_FILE_BYTES + 1))
    _as_windows(monkeypatch, tmp_path)

    assert find_local_token() is None


def test_linux_is_unsupported(monkeypatch):
    monkeypatch.setattr(local_token.platform, "system", lambda: "Linux")

    with pytest.raises(LocalTokenUnsupportedError):
        find_local_token()
    with pytest.raises(LocalTokenUnsupportedError):
        local_storage_dir()


def test_windows_without_appdata_is_reported(monkeypatch):
    monkeypatch.setattr(local_token.platform, "system", lambda: "Windows")
    monkeypatch.delenv("APPDATA", raising=False)

    with pytest.raises(LocalTokenUnsupportedError):
        find_local_token()


def test_hint_distinguishes_missing_folder_from_missing_token(tmp_path, monkeypatch):
    _as_windows(monkeypatch, tmp_path)
    assert "No se encontró la carpeta" in local_token_hint()

    _make_storage(tmp_path)
    assert "no contiene un token" in local_token_hint()


def test_hint_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(local_token.platform, "system", lambda: "Linux")

    assert "Windows y macOS" in local_token_hint()
