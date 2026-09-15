import logging
import logging.handlers

import pytest

import logging_setup


@pytest.fixture
def isolated_log_dir(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "log_directory", lambda: directory)
    return directory


def _handlers():
    return logging.getLogger().handlers


def test_creates_the_log_file(isolated_log_dir):
    path = logging_setup.configure_logging()

    assert path == isolated_log_dir / logging_setup.LOG_FILENAME
    assert path.is_file()


def test_info_records_reach_the_file_with_the_default_level(isolated_log_dir):
    logging_setup.configure_logging()
    logging.getLogger("test").info("cuenta validada")

    for handler in _handlers():
        handler.flush()

    content = (isolated_log_dir / logging_setup.LOG_FILENAME).read_text(encoding="utf-8")
    assert "cuenta validada" in content


def test_file_keeps_info_while_the_console_stays_quiet(isolated_log_dir):
    logging_setup.configure_logging("WARNING")

    file_handlers = [
        handler for handler in _handlers() if isinstance(handler, logging.FileHandler)
    ]
    console_handlers = [
        handler
        for handler in _handlers()
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]

    assert file_handlers and file_handlers[0].level == logging.INFO
    assert console_handlers and console_handlers[0].level == logging.WARNING


def test_debug_level_reaches_the_console_too(isolated_log_dir):
    logging_setup.configure_logging("DEBUG")

    console_handlers = [
        handler
        for handler in _handlers()
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]

    assert logging.getLogger().level == logging.DEBUG
    assert console_handlers and console_handlers[0].level == logging.DEBUG


def test_unknown_level_falls_back_to_warning(isolated_log_dir):
    logging_setup.configure_logging("nonsense")

    console_handlers = [
        handler
        for handler in _handlers()
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]

    assert console_handlers and console_handlers[0].level == logging.WARNING


def test_returns_none_when_the_log_cannot_be_created(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no hay espacio")

    monkeypatch.setattr(logging_setup, "RotatingFileHandler", boom)

    assert logging_setup.configure_logging() is None


def test_log_paths_live_together():
    assert logging_setup.log_file_path().parent == logging_setup.log_directory()
    assert logging_setup.log_file_path().name == logging_setup.LOG_FILENAME
