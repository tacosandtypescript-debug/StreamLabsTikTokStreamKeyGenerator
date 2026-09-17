"""The winget manifest generator."""

from __future__ import annotations

import hashlib

import pytest

from tools.make_winget_manifest import (
    MANIFEST_VERSION,
    PACKAGE_IDENTIFIER,
    PUBLISHER,
    installer_url,
    main,
    manifest_directory,
    sha256_of,
    write_manifests,
)

VERSION = "2.2.0"
INSTALLER_NAME = "Setup-StreamLabsTikTokStreamKeyGenerator-2.2.0.exe"


@pytest.fixture
def installer(tmp_path):
    path = tmp_path / INSTALLER_NAME
    path.write_bytes(b"fake installer payload")
    return path


def _manifest(installer, tmp_path, suffix):
    for path in write_manifests(installer, VERSION, tmp_path):
        if path.name.endswith(suffix):
            return path.read_text(encoding="utf-8")
    raise AssertionError(f"no manifest ending in {suffix}")


def test_the_digest_is_the_upper_case_hash_of_the_file(installer):
    expected = hashlib.sha256(installer.read_bytes()).hexdigest().upper()

    assert sha256_of(installer) == expected
    assert sha256_of(installer).isupper()


def test_the_folder_layout_is_the_one_the_pull_request_needs(tmp_path):
    directory = manifest_directory(VERSION, tmp_path)

    assert directory.parts[-5:] == (
        "manifests",
        "t",
        "tacosandtypescript-debug",
        "StreamLabsTikTokStreamKeyGenerator",
        VERSION,
    )
    assert directory.parent == tmp_path / "manifests/t/tacosandtypescript-debug" / (
        "StreamLabsTikTokStreamKeyGenerator"
    )


def test_the_installer_url_points_at_the_release_tag():
    url = installer_url(VERSION, INSTALLER_NAME)

    assert url.endswith(f"/releases/download/v{VERSION}/{INSTALLER_NAME}")
    assert url.startswith(
        "https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
    )


def test_the_three_manifests_are_written(installer, tmp_path):
    written = write_manifests(installer, VERSION, tmp_path)

    assert sorted(path.name for path in written) == sorted(
        [
            f"{PACKAGE_IDENTIFIER}.yaml",
            f"{PACKAGE_IDENTIFIER}.locale.en-US.yaml",
            f"{PACKAGE_IDENTIFIER}.installer.yaml",
        ]
    )
    assert all(path.is_file() for path in written)
    assert len({path.parent for path in written}) == 1


def test_the_version_manifest_carries_the_required_fields(installer, tmp_path):
    text = _manifest(installer, tmp_path, f"{PACKAGE_IDENTIFIER}.yaml")

    assert text.startswith("# yaml-language-server: $schema=")
    assert f"PackageIdentifier: {PACKAGE_IDENTIFIER}" in text
    assert f"PackageVersion: {VERSION}" in text
    assert "ManifestType: version" in text
    assert f"ManifestVersion: {MANIFEST_VERSION}" in text


def test_the_installer_manifest_has_the_real_hash_and_url(installer, tmp_path):
    text = _manifest(installer, tmp_path, ".installer.yaml")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest().upper()

    assert f"InstallerSha256: {digest}" in text
    assert f"InstallerUrl: {installer_url(VERSION, INSTALLER_NAME)}" in text
    assert "InstallerType: inno" in text
    assert "Scope: user" in text
    assert "Architecture: x64" in text
    assert "UpgradeBehavior: install" in text


def test_the_locale_manifest_is_english_by_default(installer, tmp_path):
    text = _manifest(installer, tmp_path, ".locale.en-US.yaml")

    assert "PackageLocale: en-US" in text
    assert f"Publisher: {PUBLISHER}" in text
    assert "License: GPL-3.0-or-later" in text
    assert "Tags:" in text


def test_manifests_are_valid_utf8_without_a_bom(installer, tmp_path):
    for path in write_manifests(installer, VERSION, tmp_path):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        raw.decode("utf-8")


def test_a_missing_installer_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_manifests(tmp_path / "missing.exe", VERSION, tmp_path)


def test_the_cli_reports_a_failure_without_a_traceback(tmp_path, capsys):
    exit_code = main(
        [
            "--installer",
            str(tmp_path / "missing.exe"),
            "--version",
            VERSION,
            "--output",
            str(tmp_path),
        ]
    )

    assert exit_code == 1
    assert "No se pudieron generar" in capsys.readouterr().err


def test_the_cli_writes_the_manifests(installer, tmp_path, capsys):
    exit_code = main(
        [
            "--installer",
            str(installer),
            "--version",
            VERSION,
            "--output",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert "installer.yaml" in capsys.readouterr().out
