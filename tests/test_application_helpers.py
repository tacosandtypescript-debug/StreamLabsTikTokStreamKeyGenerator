import pytest

# Importing the GUI module pulls in Qt, which a headless Linux runner can only
# import once the system Qt libraries are present. Skip instead of failing.
pytest.importorskip("PySide6.QtWidgets")

import StreamLabsTikTokStreamKeyGenerator as application  # noqa: E402


def test_local_token_reader_is_limited_to_known_windows_path(tmp_path, monkeypatch):
    base = tmp_path / "slobs-client" / "Local Storage" / "leveldb"
    base.mkdir(parents=True)
    token = "a" * 32
    (base / "000001.log").write_bytes(f'{{"apiToken":"{token}"}}'.encode("ascii"))
    monkeypatch.setattr(application.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert application.StreamApp._find_local_token() == token


def test_local_token_reader_returns_none_when_directory_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(application.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert application.StreamApp._find_local_token() is None


def test_local_token_reader_reports_linux_fallback(monkeypatch):
    monkeypatch.setattr(application.platform, "system", lambda: "Linux")

    with pytest.raises(application.LocalTokenUnsupportedError):
        application.StreamApp._find_local_token()


def test_safe_error_message_hides_unexpected_exceptions():
    assert application.StreamApp._safe_error_message(RuntimeError("secret detail")) == (
        "La operación no pudo completarse. Revisa la conexión y vuelve a intentarlo."
    )
    assert application.StreamApp._safe_error_message(ValueError("mensaje claro")) == (
        "mensaje claro"
    )
