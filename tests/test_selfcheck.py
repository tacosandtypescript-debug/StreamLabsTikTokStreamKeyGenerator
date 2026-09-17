"""The self-check a packaged build can run about itself."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from selfcheck import CheckResult, SelfCheckReport, run_self_check
from version import __version__


class _NoTokens:
    """A token store that has nothing, so no test ever reaches the system keyring."""

    def get_token(self):
        return None

    def save_token(self, token):
        return False


def test_a_report_with_nothing_wrong_is_healthy():
    report = SelfCheckReport()
    report.add(CheckResult("Qt y plataforma", True, "offscreen"))

    assert report.ok is True
    assert report.failed == []
    assert "puede funcionar" in report.text()


def test_a_critical_failure_makes_the_check_fail():
    report = SelfCheckReport()
    report.add(CheckResult("Las dos pantallas existen", False, "0 pantallas"))

    assert report.ok is False
    assert [item.name for item in report.failed] == ["Las dos pantallas existen"]
    assert "FALLO" in report.text()
    assert "Las dos pantallas existen" in report.text()


def test_a_cosmetic_surprise_is_only_a_warning():
    report = SelfCheckReport()
    report.add(CheckResult("Icono de la aplicación", False, "no cargó", critical=False))

    assert report.ok is True
    assert "aviso" in report.text()


def test_the_report_names_the_version():
    assert __version__ in SelfCheckReport().text()


def test_the_check_of_a_real_window_passes(qtbot, tmp_path, capsys, monkeypatch):
    # Theming is not what is being checked here, and applying it would change the
    # session's font and stylesheet for every other test.
    monkeypatch.setattr("ui.theme.apply_theme", lambda *args, **kwargs: "light")
    from config_store import ConfigStore
    from ui.main_window import StreamApp

    window = StreamApp(
        config_store=ConfigStore(tmp_path / "config.json"),
        token_store=_NoTokens(),
    )
    qtbot.addWidget(window)

    code = run_self_check(window_factory=lambda: window)

    printed = capsys.readouterr().out
    assert code == 0
    assert "Autocomprobación" in printed
    assert "puede funcionar" in printed


def test_the_check_fails_loudly_on_a_broken_window(qtbot, capsys):
    # A window with nothing inside stands in for a bundle missing its pieces.
    broken = QWidget()
    qtbot.addWidget(broken)

    code = run_self_check(window_factory=lambda: broken)

    printed = capsys.readouterr().out
    assert code == 1
    assert "FALLO" in printed
    assert "Ventana con tamaño utilizable" in printed


def test_the_check_asks_for_a_screen_that_does_not_need_a_display(monkeypatch):
    # Without this, a build could only be checked on a machine with a desktop, which
    # is exactly what continuous integration is not.
    seen: dict[str, str] = {}
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(
        "os.environ.setdefault",
        lambda key, value: seen.setdefault(key, value),
    )

    run_self_check(window_factory=QWidget)

    assert seen.get("QT_QPA_PLATFORM") == "offscreen"


def test_the_report_is_written_where_it_can_be_read(tmp_path, monkeypatch, capsys):
    # A packaged Windows build has no console, so the exit code alone would say
    # "something is wrong" without saying what.
    monkeypatch.setattr("logging_setup.log_directory", lambda: tmp_path)

    run_self_check(window_factory=QWidget)

    written = tmp_path / "autocomprobacion.txt"
    assert written.is_file()
    assert "Autocomprobación" in written.read_text(encoding="utf-8")
    assert str(written) in capsys.readouterr().out


def test_a_report_that_cannot_be_written_does_not_break_the_check(monkeypatch):
    monkeypatch.setattr("selfcheck._write_report", lambda text: None)

    assert run_self_check(window_factory=QWidget) == 1
