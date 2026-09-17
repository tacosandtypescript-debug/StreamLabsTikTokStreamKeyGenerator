import hashlib
import os
import threading
from pathlib import Path

import pytest

import Updater
from Updater import (
    ChecksumMismatchError,
    DownloadCancelled,
    DownloadError,
    VersionChecker,
    can_self_install,
    download_asset,
    fetch_checksum,
    installer_helper_script,
    is_installer_asset,
    launch_detached,
    parse_checksum,
    select_asset,
    write_installer_helper,
)
from version import __version__

EXPECTED_REPO = "tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"

RELEASE = {
    "tag_name": "v2.0.0",
    "html_url": "https://github.com/release",
    "body": "notes",
    "assets": [
        {
            "name": "StreamLabs-win-2.0.0.zip",
            "browser_download_url": "https://x/win.zip",
            "size": 10,
        },
        {
            "name": "StreamLabs-arm64-macos-2.0.0.zip",
            "browser_download_url": "https://x/mac.zip",
            "size": 10,
        },
        {
            "name": "SHA256SUMS.txt",
            "browser_download_url": "https://x/SHA256SUMS.txt",
            "size": 5,
        },
    ],
}


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200, headers=None, chunks=()):
        self.payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Updater.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_source_checkout_has_version_fallback():
    assert isinstance(__version__, str)
    assert __version__


def test_update_checker_returns_release_info(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "1.0.0")

    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse(RELEASE))

    assert result["latest"] == "2.0.0"
    assert result["url"] == "https://github.com/release"
    assert result["current"] == "1.0.0"
    assert result["notes"] == "notes"


def test_update_checker_exposes_assets_and_checksums(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "1.0.0")

    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse(RELEASE))

    assert result["checksums_url"] == "https://x/SHA256SUMS.txt"
    assert [asset["name"] for asset in result["assets"]] == [
        "StreamLabs-win-2.0.0.zip",
        "StreamLabs-arm64-macos-2.0.0.zip",
        "SHA256SUMS.txt",
    ]


def test_update_checker_is_silent_for_newer_current_version(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "2.0.0")

    assert VersionChecker.check_update(http_get=lambda *a, **k: FakeResponse(RELEASE)) is None


def test_update_checker_never_nags_from_a_source_checkout(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "0.0.0-dev")

    assert VersionChecker.check_update(http_get=lambda *a, **k: FakeResponse(RELEASE)) is None


def test_update_checker_points_at_this_repository():
    assert VersionChecker.REPO == EXPECTED_REPO
    assert EXPECTED_REPO in VersionChecker.API_URL


def test_update_checker_survives_a_broken_response(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "1.0.0")

    result = VersionChecker.check_update(
        http_get=lambda *a, **k: FakeResponse(status_code=500)
    )

    assert result is None


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Windows", "AMD64", "StreamLabs-win-2.0.0.zip"),
        ("Darwin", "arm64", "StreamLabs-arm64-macos-2.0.0.zip"),
        ("Linux", "x86_64", None),
        ("FreeBSD", "", None),
    ],
)
def test_select_asset_picks_the_package_for_the_platform(system, machine, expected):
    # select_asset works on the normalised assets produced by check_update.
    assets = [
        {"name": asset["name"], "url": asset["browser_download_url"]}
        for asset in RELEASE["assets"]
    ]

    selected = select_asset(assets, system, machine)

    assert (selected or {}).get("name") == expected


def test_select_asset_ignores_non_zip_files():
    assets = [{"name": "SHA256SUMS.txt", "url": "u"}, {"name": "notes.md", "url": "u"}]

    assert select_asset(assets, "Windows") is None


def test_parse_checksum_handles_paths_and_the_binary_marker():
    text = (
        "a" * 64
        + "  windows/StreamLabs-win-2.0.0.zip\n"
        + "f" * 64
        + " *StreamLabs-linux-2.0.0.zip\n"
    )

    assert parse_checksum(text, "StreamLabs-win-2.0.0.zip") == "a" * 64
    assert parse_checksum(text, "StreamLabs-linux-2.0.0.zip") == "f" * 64
    assert parse_checksum(text, "missing.zip") is None


@pytest.mark.parametrize(
    "text",
    ["", "nonsense\n", "xyz  a.zip", "a" * 63 + "  a.zip", "z" * 64 + "  a.zip"],
)
def test_parse_checksum_rejects_malformed_lines(text):
    assert parse_checksum(text, "a.zip") is None


def test_fetch_checksum_reads_the_release_file():
    response = FakeResponse(text="b" * 64 + "  StreamLabs-win-2.0.0.zip\n")

    digest = fetch_checksum(
        "https://x/SHA256SUMS.txt",
        "StreamLabs-win-2.0.0.zip",
        http_get=lambda *a, **k: response,
    )

    assert digest == "b" * 64


def test_fetch_checksum_reports_network_failures():
    with pytest.raises(DownloadError):
        fetch_checksum(
            "https://x/SHA256SUMS.txt",
            "a.zip",
            http_get=lambda *a, **k: FakeResponse(status_code=500),
        )


def test_download_writes_the_file_and_reports_progress(tmp_path):
    payload = b"x" * 5000
    digest = hashlib.sha256(payload).hexdigest()
    chunks = [payload[index : index + 1024] for index in range(0, len(payload), 1024)]
    seen = []

    target = download_asset(
        "https://x/app.zip",
        tmp_path / "app.zip",
        http_get=lambda *a, **k: FakeResponse(
            headers={"Content-Length": str(len(payload))}, chunks=chunks
        ),
        expected_sha256=digest,
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert target.read_bytes() == payload
    assert seen[-1] == (len(payload), len(payload))
    assert not (tmp_path / "app.zip.part").exists()


def test_download_accepts_a_checksum_in_upper_case(tmp_path):
    payload = b"y" * 64
    digest = hashlib.sha256(payload).hexdigest().upper()

    target = download_asset(
        "https://x/app.zip",
        tmp_path / "app.zip",
        http_get=lambda *a, **k: FakeResponse(chunks=[payload]),
        expected_sha256=digest,
    )

    assert target.exists()


def test_download_discards_a_file_that_does_not_match(tmp_path):
    with pytest.raises(ChecksumMismatchError):
        download_asset(
            "https://x/app.zip",
            tmp_path / "app.zip",
            http_get=lambda *a, **k: FakeResponse(chunks=[b"tampered"]),
            expected_sha256="0" * 64,
        )

    assert not (tmp_path / "app.zip").exists()
    assert not (tmp_path / "app.zip.part").exists()


def test_download_can_be_cancelled(tmp_path):
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(DownloadCancelled):
        download_asset(
            "https://x/app.zip",
            tmp_path / "app.zip",
            http_get=lambda *a, **k: FakeResponse(chunks=[b"data"]),
            cancel=cancel,
        )

    assert not (tmp_path / "app.zip.part").exists()


def test_download_reports_network_errors(tmp_path):
    with pytest.raises(DownloadError):
        download_asset(
            "https://x/app.zip",
            tmp_path / "app.zip",
            http_get=lambda *a, **k: FakeResponse(status_code=404),
        )


# --------------------------------------------------------------------------- #
#  The Windows installer                                                      #
# --------------------------------------------------------------------------- #

INSTALLER_ASSET = {
    "name": "Setup-StreamLabsTikTokStreamKeyGenerator-2.0.0.exe",
    "browser_download_url": "https://x/setup.exe",
    "size": 20,
}


def _normalised(*entries):
    return [{"name": entry["name"], "url": entry["browser_download_url"]} for entry in entries]


def test_the_windows_installer_is_preferred_over_the_archive():
    assets = _normalised(RELEASE["assets"][0], INSTALLER_ASSET)

    selected = select_asset(assets, "Windows")

    assert selected is not None
    assert selected["name"] == INSTALLER_ASSET["name"]


def test_the_archive_is_used_when_the_release_has_no_installer():
    selected = select_asset(_normalised(RELEASE["assets"][0]), "Windows")

    assert selected is not None
    assert selected["name"] == "StreamLabs-win-2.0.0.zip"


def test_the_installer_can_be_left_out_on_request():
    assets = _normalised(RELEASE["assets"][0], INSTALLER_ASSET)

    selected = select_asset(assets, "Windows", prefer_installer=False)

    assert selected is not None
    assert selected["name"] == "StreamLabs-win-2.0.0.zip"


def test_an_installer_is_never_selected_for_another_platform():
    assets = _normalised(INSTALLER_ASSET)

    assert select_asset(assets, "Linux") is None
    assert select_asset(assets, "Darwin") is None


@pytest.mark.parametrize(
    ("name", "system", "expected"),
    [
        ("Setup-App-1.0.0.exe", "Windows", True),
        ("Setup-App-1.0.0.zip", "Windows", False),
        ("App-1.0.0.exe", "Windows", False),
        ("Setup-App-1.0.0.exe", "Linux", False),
        ("Setup-App-1.0.0.exe", "Darwin", False),
        (None, "Windows", False),
    ],
)
def test_installer_detection_is_strict(name, system, expected):
    assert is_installer_asset({"name": name}, system) is expected


def test_self_install_requires_a_frozen_windows_build(monkeypatch):
    monkeypatch.setattr(Updater, "is_frozen", lambda: True)

    assert can_self_install("Windows", INSTALLER_ASSET) is True
    assert can_self_install("Linux", INSTALLER_ASSET) is False
    assert can_self_install("Darwin", INSTALLER_ASSET) is False
    assert can_self_install("Windows", None) is False
    assert can_self_install("Windows", {"name": "App-2.0.0.zip"}) is False


def test_a_source_checkout_never_replaces_itself(monkeypatch):
    monkeypatch.setattr(Updater, "is_frozen", lambda: False)

    assert can_self_install("Windows", INSTALLER_ASSET) is False


def test_the_helper_runs_the_installer_silently_and_relaunches():
    script = installer_helper_script(
        installer=Path(r"C:\Users\a\Downloads\Setup-App-2.0.0.exe"),
        app_executable=Path(r"C:\Users\a\App\App.exe"),
        log_path=Path(r"C:\Users\a\Downloads\actualizacion.log"),
        delay_seconds=5,
    )
    lines = script.splitlines()

    assert lines[0] == "@echo off"
    assert "timeout /t 5 /nobreak >NUL" in lines
    install_line = next(line for line in lines if "/SILENT" in line)
    for flag in ("/SILENT", "/CLOSEAPPLICATIONS", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"):
        assert flag in install_line
    assert r'/LOG="C:\Users\a\Downloads\actualizacion.log"' in install_line
    assert r'start "" "C:\Users\a\App\App.exe"' in script


def test_the_helper_does_not_relaunch_without_an_executable():
    script = installer_helper_script(installer=Path(r"C:\x\Setup.exe"))

    assert "start " not in script


def test_the_helper_can_skip_the_delay():
    script = installer_helper_script(installer=Path(r"C:\x\Setup.exe"), delay_seconds=0)

    assert "timeout" not in script


def test_a_percent_in_a_path_is_escaped_for_batch():
    script = installer_helper_script(installer=Path(r"C:\100%\Setup.exe"))

    assert r'"C:\100%%\Setup.exe"' in script


def test_the_helper_is_written_once_per_process(tmp_path):
    helper = write_installer_helper(tmp_path / "sub", installer=Path(r"C:\x\Setup.exe"))

    assert helper.is_file()
    assert helper.parent == tmp_path / "sub"
    assert helper.suffix == ".cmd"
    assert str(os.getpid()) in helper.name
    assert helper.read_text(encoding="utf-8").startswith("@echo off")


def test_launching_the_helper_is_detached(monkeypatch, tmp_path):
    calls = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs

    monkeypatch.setattr(Updater.subprocess, "Popen", FakePopen)

    launch_detached(tmp_path / "helper.cmd")

    assert calls["kwargs"]["close_fds"] is True
    if os.name == "nt":
        assert calls["args"][0] == "cmd.exe"
        assert calls["kwargs"]["creationflags"] & Updater.subprocess.DETACHED_PROCESS
    else:
        assert calls["args"][0] == "/bin/sh"
        assert calls["kwargs"]["start_new_session"] is True
