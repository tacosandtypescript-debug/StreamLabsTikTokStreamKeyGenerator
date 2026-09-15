import hashlib
import threading

import pytest

import Updater
from Updater import (
    ChecksumMismatchError,
    DownloadCancelled,
    DownloadError,
    VersionChecker,
    download_asset,
    fetch_checksum,
    parse_checksum,
    select_asset,
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
