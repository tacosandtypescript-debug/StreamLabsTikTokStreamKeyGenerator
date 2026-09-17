"""GUI logic tests.

These run the real widgets offscreen (``QT_QPA_PLATFORM=offscreen`` in CI) and
avoid every modal dialog and network call, so they stay fast and deterministic.
"""

import zipfile

import pytest
from PySide6.QtGui import QCloseEvent, QShortcut

from config_store import ActiveSession, AppConfig, ConfigStore, read_config_file
from secure_store import ACCOUNT_NAME, SERVICE_NAME, SecureTokenStore
from streamlabs_client import (
    AccountInfo,
    AuthenticationError,
    StreamlabsError,
    StreamSession,
)
from ui import main_window as application
from ui.main_window import StreamApp
from ui.shortcuts import SHORTCUTS


class FakeBackend:
    """Minimal stand-in for a keyring backend."""

    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return self

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, password):
        self.values[(service, account)] = password

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class FakeClient:
    """Records calls instead of talking to Streamlabs."""

    instances = []

    def __init__(self, token, *args, **kwargs):
        self.token = token
        self.ended = []
        FakeClient.instances.append(self)

    def get_account_info(self):
        return AccountInfo("creator", "approved", True)

    def search_categories(self, query):
        return []

    def start_stream(self, title, category_id, audience_type="0"):
        return StreamSession("session-1", "rtmp://server", "STREAMKEY-SECRET")

    def end_stream(self, session_id):
        self.ended.append(session_id)


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "config.json")


@pytest.fixture
def app(qtbot, store, backend, monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(application, "StreamlabsTikTokClient", FakeClient)
    # No dialog may block a test.
    monkeypatch.setattr(application.QMessageBox, "exec", lambda self: 0)
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(application.QMessageBox, name, staticmethod(lambda *a, **k: None))

    window = application.StreamApp(
        config_store=store,
        token_store=SecureTokenStore(backend=backend),
    )
    qtbot.addWidget(window)
    return window


def _validated(app, token="token-value"):
    app.token_entry.setText(token)
    app._validated_token = token
    app._account_info = AccountInfo("creator", "approved", True)
    app.stream_title.setText("Title")
    return app


# --------------------------------------------------------------------------- #
#  Preparación del directo                                                     #
# --------------------------------------------------------------------------- #


def test_cannot_start_without_a_validated_account(app):
    app.stream_title.setText("Title")
    app.game_category.setText("Fortnite")

    assert app._can_start_stream() is False
    assert app.go_live_btn.isEnabled() is False


def test_can_start_with_account_title_and_resolved_category(app):
    _validated(app)
    app.game_category.setText("Fortnite")
    app._category_id = "42"

    assert app._can_start_stream() is True

    app._update_controls()
    assert app.go_live_btn.isEnabled() is True


def test_other_category_needs_no_resolved_id(app):
    _validated(app)
    app.game_category.setText("Other")
    app._category_id = ""

    assert app._can_start_stream() is True


def test_unresolved_category_blocks_start(app):
    _validated(app)
    app.game_category.setText("Fortnite")
    app._category_id = ""

    assert app._can_start_stream() is False


def test_account_without_live_permission_blocks_start(app):
    _validated(app)
    app._account_info = AccountInfo("creator", "pending", False)
    app.game_category.setText("Other")

    assert app._can_start_stream() is False

    app._update_controls()
    assert app.go_live_btn.isEnabled() is False


def test_stream_title_and_category_are_locked_while_live(app):
    _validated(app)
    app.game_category.setText("Other")
    app._active_session = StreamSession("session-1", "rtmp://server", "key")

    app._update_controls()

    assert app.stream_title.isEnabled() is False
    assert app.end_live_btn.isEnabled() is True
    assert app._can_start_stream() is False


def test_save_token_button_requires_a_validated_token(app, backend):
    app.token_entry.setText("token-value")

    app._update_controls()
    assert app.save_token_btn.isEnabled() is False
    assert backend.values == {}

    app._validated_token = "token-value"
    app._update_controls()
    assert app.save_token_btn.isEnabled() is True


# --------------------------------------------------------------------------- #
#  Session bookkeeping                                                        #
# --------------------------------------------------------------------------- #


def test_starting_a_session_is_recorded_without_secrets(app, store):
    _validated(app)
    app.game_category.setText("Other")

    app._stream_started(StreamSession("session-1", "rtmp://server", "STREAMKEY-SECRET"))

    saved = read_config_file(store.path)
    assert saved.config.active_session is not None
    assert saved.config.active_session.session_id == "session-1"
    assert saved.config.active_session.title == "Title"
    assert saved.config.active_session.started_at
    assert "STREAMKEY-SECRET" not in store.path.read_text(encoding="utf-8")


def test_ending_a_session_clears_the_record(app, store):
    _validated(app)
    app._stream_started(StreamSession("session-1", "rtmp://server", "STREAMKEY-SECRET"))

    app._stream_ended()

    assert read_config_file(store.path).config.active_session is None


def test_failed_ending_keeps_session_available_for_retry(app):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    app._session_record = ActiveSession("session-1", "Title")

    app._stream_end_failed(StreamlabsError("hidden", status_code=503))

    assert app._active_session is not None
    assert app._session_record is not None
    assert "reintentarlo" in app.app_status.text()


def test_leftover_session_can_be_forgotten(app, store):
    app._session_record = ActiveSession("session-1", "Title", "2026-01-01T00:00:00+00:00")

    app._handle_pending_session_choice("forget")

    assert app._session_record is None
    assert read_config_file(store.path).config.active_session is None


def test_leftover_session_is_kept_when_no_token_is_validated(app):
    app._session_record = ActiveSession("session-1")

    app._handle_pending_session_choice("close")

    assert app._session_record is not None
    assert "Valida el token" in app.app_status.text()


def test_leftover_session_is_closed_through_the_api(app, store):
    app._session_record = ActiveSession("session-1")
    app.token_entry.setText("token-value")
    app._validated_token = "token-value"

    app._handle_pending_session_choice("close")
    app.thread_pool.waitForDone(5000)

    assert FakeClient.instances
    assert FakeClient.instances[-1].ended == ["session-1"]


def test_startup_warns_when_a_session_is_pending(app):
    app._session_record = ActiveSession("session-1")

    app._check_pending_session()

    assert "sesión anterior sin cerrar" in app.app_status.text()


# --------------------------------------------------------------------------- #
#  Legacy plaintext token                                                     #
# --------------------------------------------------------------------------- #


def _legacy_file(tmp_path, body='{"token": "plaintext-token", "title": "Old"}'):
    path = tmp_path / "legacy.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_declining_never_loads_the_plaintext_token(app, store, tmp_path):
    legacy = _legacy_file(tmp_path)
    result = read_config_file(legacy)

    app._handle_legacy_choice("decline", legacy, result)

    assert app.token_entry.text() == ""
    assert app._validated_token is None
    assert legacy.exists()
    assert "plaintext-token" in legacy.read_text(encoding="utf-8")
    assert read_config_file(store.path).config.legacy_migration_declined is True


def test_deleting_removes_the_plaintext_file(app, tmp_path):
    legacy = _legacy_file(tmp_path)
    result = read_config_file(legacy)

    app._handle_legacy_choice("delete", legacy, result)

    assert not legacy.exists()
    assert app.token_entry.text() == ""


def test_importing_moves_the_token_to_the_keyring(app, backend, tmp_path):
    legacy = _legacy_file(tmp_path)
    result = read_config_file(legacy)

    app._handle_legacy_choice("import", legacy, result)

    assert backend.values[(SERVICE_NAME, ACCOUNT_NAME)] == "plaintext-token"
    assert app.token_entry.text() == "plaintext-token"
    assert "plaintext-token" not in legacy.read_text(encoding="utf-8")


def test_importing_keeps_the_token_when_the_store_is_unavailable(app, tmp_path, monkeypatch):
    class BrokenBackend(FakeBackend):
        def set_password(self, service, account, password):
            raise RuntimeError("no keyring")

    app.token_store = SecureTokenStore(backend=BrokenBackend())
    legacy = _legacy_file(tmp_path)
    result = read_config_file(legacy)

    app._handle_legacy_choice("import", legacy, result)

    # The plaintext file is left alone and nothing is loaded behind the user's back.
    assert "plaintext-token" in legacy.read_text(encoding="utf-8")
    assert app._legacy_migration_declined is True


# --------------------------------------------------------------------------- #
#  Shutdown                                                                   #
# --------------------------------------------------------------------------- #


def test_closing_cancels_a_pending_web_login(app):
    class FakeRetriever:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    retriever = FakeRetriever()
    app._online_retriever = retriever

    app.closeEvent(QCloseEvent())

    assert retriever.cancelled is True


def test_config_from_ui_keeps_the_session_record(app):
    _validated(app)
    app._session_record = ActiveSession("session-1", "Title")

    config = app._config_from_ui()

    assert isinstance(config, AppConfig)
    assert config.active_session == ActiveSession("session-1", "Title")


# --------------------------------------------------------------------------- #
#  Closing with a session still open                                          #
# --------------------------------------------------------------------------- #


def test_close_event_tears_down_when_nothing_is_live(app):
    event = QCloseEvent()

    app.closeEvent(event)

    assert event.isAccepted() is True
    assert app._closing is True


def test_closing_with_a_live_session_ends_it_first(app, monkeypatch):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    ended = []
    monkeypatch.setattr(app, "end_stream", lambda: ended.append(True))
    event = QCloseEvent()

    app._handle_close_choice("end", event)

    assert ended == [True]
    # The window has to stay alive until Streamlabs has answered.
    assert event.isAccepted() is False
    assert app._closing_after_end is True


def test_cancelling_the_close_changes_nothing(app):
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    event = QCloseEvent()

    app._handle_close_choice("cancel", event)

    assert event.isAccepted() is False
    assert app._active_session is not None
    assert app._closing is False


def test_keeping_the_session_closes_anyway(app):
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    event = QCloseEvent()

    app._handle_close_choice("keep", event)

    assert event.isAccepted() is True
    assert app._closing is True


def test_closing_cannot_end_a_session_without_a_validated_token(app, monkeypatch):
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    monkeypatch.setattr(app, "_ask_close_with_active_session", lambda: "end")
    event = QCloseEvent()

    app.closeEvent(event)

    assert event.isAccepted() is False
    assert app._closing_after_end is False
    assert "Espera" in app.app_status.text()


def test_the_window_closes_itself_once_the_session_ended(app, monkeypatch):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    app._closing_after_end = True
    closed = []
    monkeypatch.setattr(app, "close", lambda: closed.append(True))

    app._stream_ended()

    assert closed == [True]
    assert app._closing_after_end is False


def test_a_failed_end_can_still_close_when_the_user_insists(app, monkeypatch):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    app._closing_after_end = True
    closed = []
    monkeypatch.setattr(app, "close", lambda: closed.append(True))
    monkeypatch.setattr(app, "_ask_abandon_failed_end", lambda: True)

    app._stream_end_failed(StreamlabsError("boom", status_code=503))

    assert closed == [True]


def test_a_failed_end_stays_open_when_the_user_prefers_to_retry(app, monkeypatch):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    app._closing_after_end = True
    closed = []
    monkeypatch.setattr(app, "close", lambda: closed.append(True))
    monkeypatch.setattr(app, "_ask_abandon_failed_end", lambda: False)

    app._stream_end_failed(StreamlabsError("boom", status_code=503))

    assert closed == []
    assert app._closing_after_end is False


# --------------------------------------------------------------------------- #
#  Expired token                                                              #
# --------------------------------------------------------------------------- #


def test_a_rejected_token_offers_a_new_web_login(app, monkeypatch):
    started = []
    monkeypatch.setattr(app, "fetch_online_token", lambda: started.append(True))

    app._handle_token_renewal_choice("renew")

    assert started == [True]


def test_declining_the_renewal_explains_what_to_do(app):
    app._handle_token_renewal_choice("later")

    assert "caducado" in app.app_status.text()


def test_an_expired_token_offers_renewal_instead_of_a_generic_error(app, qtbot, monkeypatch):
    prompts = []
    fallbacks = []
    monkeypatch.setattr(app, "_prompt_token_renewal", lambda: prompts.append(True))

    def boom():
        raise AuthenticationError("El token caducó")

    app._run_worker(boom, lambda _result: None, fallbacks.append)

    qtbot.waitUntil(lambda: bool(prompts), timeout=5000)
    assert prompts == [True]
    assert fallbacks == []


def test_a_silent_validation_never_pops_the_renewal_dialog(app, qtbot, monkeypatch):
    prompts = []
    monkeypatch.setattr(app, "_prompt_token_renewal", lambda: prompts.append(True))

    def boom():
        raise AuthenticationError("El token caducó")

    app._run_worker(
        boom,
        lambda _result: None,
        lambda _exc: None,
        offer_token_renewal=False,
    )

    app.thread_pool.waitForDone(5000)
    qtbot.wait(50)

    assert prompts == []


# --------------------------------------------------------------------------- #
#  Window geometry and shortcuts                                              #
# --------------------------------------------------------------------------- #


def test_the_window_size_and_position_survive_a_restart(app, store, qtbot):
    app.resize(1234, 876)
    app.move(60, 40)
    assert app.save_config(False) is True

    second = StreamApp(config_store=store, token_store=app.token_store)
    qtbot.addWidget(second)

    assert (second.width(), second.height()) == (1234, 876)
    assert (second.x(), second.y()) == (60, 40)


def test_a_remembered_position_with_no_screen_left_is_ignored(app, store, qtbot):
    app.resize(1000, 700)
    app.save_config(False)
    saved = app.config_store.load().config
    app.config_store.save(
        AppConfig(
            title=saved.title,
            game=saved.game,
            window_width=1000,
            window_height=700,
            window_x=40000,
            window_y=40000,
        )
    )

    second = StreamApp(config_store=store, token_store=app.token_store)
    qtbot.addWidget(second)

    assert (second.width(), second.height()) == (1000, 700)
    assert (second.x(), second.y()) != (40000, 40000)


def test_every_configured_shortcut_targets_a_real_method(app):
    for _sequence, method_name in SHORTCUTS:
        assert callable(getattr(app, method_name)), method_name


def test_the_window_installs_one_shortcut_per_entry(app):
    installed = app.findChildren(QShortcut)

    assert len(installed) == len(SHORTCUTS)
    assert {shortcut.key().toString() for shortcut in installed} == {
        sequence for sequence, _ in SHORTCUTS
    }


def test_a_shortcut_invokes_the_method_it_points_at(app):
    calls = []
    app.end_stream = lambda: calls.append("end")
    shortcut = next(
        item
        for item in app.findChildren(QShortcut)
        if item.key().toString() == "Ctrl+Shift+Return"
    )

    shortcut.activated.emit()

    assert calls == ["end"]


# --------------------------------------------------------------------------- #
#  Diagnostic report                                                          #
# --------------------------------------------------------------------------- #


def test_exporting_diagnostics_writes_a_report_without_secrets(app, tmp_path, monkeypatch):
    log = tmp_path / "app.log"
    log.write_text("2026-01-01 INFO streamlabs_client: cuenta validada\n", encoding="utf-8")
    destination = tmp_path / "diagnostico.zip"
    monkeypatch.setattr(application, "default_report_path", lambda: destination)
    monkeypatch.setattr(application, "log_file_path", lambda: log)
    app.token_entry.setText("SUPER-SECRET-TOKEN")
    app.stream_key.setText("SUPER-SECRET-KEY")

    app.export_diagnostics()

    assert destination.is_file()
    with zipfile.ZipFile(destination) as archive:
        content = "\n".join(
            archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()
        )
    assert "SUPER-SECRET-TOKEN" not in content
    assert "SUPER-SECRET-KEY" not in content
    assert "cuenta validada" in content
    assert "Informe de diagnóstico" in content


def test_a_failed_diagnostics_export_tells_the_user(app, tmp_path, monkeypatch):
    blocked = tmp_path / "archivo" / "diagnostico.zip"
    blocked.parent.write_text("esto no es una carpeta", encoding="utf-8")
    monkeypatch.setattr(application, "default_report_path", lambda: blocked)
    warnings = []
    monkeypatch.setattr(
        application.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    app.export_diagnostics()

    assert warnings


def test_the_support_menu_offers_both_support_actions(app):
    labels = [action.text() for action in app.support_btn.menu().actions()]

    assert labels == [
        "Abrir la carpeta de registros",
        "Guardar informe de diagnóstico",
    ]
