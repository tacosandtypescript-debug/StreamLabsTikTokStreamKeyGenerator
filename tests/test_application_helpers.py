import pytest

import StreamLabsTikTokStreamKeyGenerator as application
from streamlabs_client import StreamlabsTikTokClient


def test_local_token_reader_is_limited_to_known_windows_path(tmp_path, monkeypatch):
    base = tmp_path / "slobs-client" / "Local Storage" / "leveldb"
    base.mkdir(parents=True)
    token = "a" * 32
    (base / "000001.log").write_bytes(f'{{"apiToken":"{token}"}}'.encode("ascii"))
    monkeypatch.setattr(application.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert application.StreamApp._find_local_token() == token


def test_local_token_reader_reports_linux_fallback(monkeypatch):
    monkeypatch.setattr(application.platform, "system", lambda: "Linux")

    with pytest.raises(application.LocalTokenUnsupportedError):
        application.StreamApp._find_local_token()


def test_device_platform_is_mapped(monkeypatch):
    monkeypatch.setattr(application.platform, "system", lambda: "Darwin")

    assert StreamlabsTikTokClient._device_platform() == "darwin"
