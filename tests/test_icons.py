"""Locating and loading the artwork that ships with the application."""

from __future__ import annotations

from ui.icons import (
    DEFAULT_ICON_FILE,
    application_icon,
    assets_directory,
    icon_file_name,
    icon_path,
    is_frozen,
)


def test_a_source_checkout_finds_the_assets():
    directory = assets_directory()

    assert directory is not None
    assert directory.name == "assets"
    assert (directory / DEFAULT_ICON_FILE).is_file()


def test_each_platform_gets_the_icon_file_it_can_read():
    assert icon_file_name("Windows") == "icon.ico"
    assert icon_file_name("Darwin") == "icon.icns"
    assert icon_file_name("Linux") == DEFAULT_ICON_FILE
    assert icon_file_name("FreeBSD") == DEFAULT_ICON_FILE


def test_a_missing_platform_icon_falls_back_to_the_png(tmp_path, monkeypatch):
    (tmp_path / DEFAULT_ICON_FILE).write_bytes(b"placeholder")
    monkeypatch.setattr("ui.icons.assets_directory", lambda: tmp_path)

    assert icon_path("Windows") == tmp_path / DEFAULT_ICON_FILE


def test_a_missing_icon_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.icons.assets_directory", lambda: None)

    assert icon_path("Windows") is None
    assert application_icon("Windows") is None


def test_an_empty_assets_directory_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.icons.assets_directory", lambda: tmp_path)

    assert icon_path("Windows") is None


def test_the_shipped_windows_icon_really_loads(qapp):
    # This is the end-to-end check that the .ico is a valid image: Qt has to be
    # able to decode the file that ends up on the executable.
    icon = application_icon("Windows")

    assert icon is not None
    assert icon.isNull() is False


def test_the_shipped_png_really_loads(qapp):
    icon = application_icon("Linux")

    assert icon is not None
    assert icon.isNull() is False


def test_a_source_checkout_is_not_frozen():
    assert is_frozen() is False
