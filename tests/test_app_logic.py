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


def test_a_deferred_callback_is_dropped_for_a_window_that_is_not_visible(app, qtbot):
    # Qt sends no close event to a widget that is not visible, so such a window
    # can be awaiting deletion while its timers are still armed. Running a modal
    # dialog then outlives the window.
    calls = []
    app._defer(10, lambda: calls.append(True))

    qtbot.wait(80)

    assert app.isVisible() is False
    assert calls == []


def test_a_deferred_callback_runs_for_a_visible_window(app, qtbot):
    calls = []
    app.show()
    app._defer(10, lambda: calls.append(True))

    qtbot.waitUntil(lambda: bool(calls), timeout=2000)

    assert calls == [True]


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


def test_the_more_menu_keeps_the_secondary_actions_out_of_the_way(app):
    labels = [
        action.text()
        for action in app.support_btn.menu().actions()
        if not action.isSeparator()
    ]

    assert labels == [
        "Abrir la carpeta de registros",
        "Guardar informe de diagnóstico",
        "Ayuda",
        "Abrir monitor de TikTok",
        "Donar al autor original",
    ]


# --------------------------------------------------------------------------- #
#  What the window says about itself                                         #
# --------------------------------------------------------------------------- #


def test_the_banner_starts_without_a_token(app):
    app._refresh_banner()

    assert app.banner.state() == "neutral"
    assert "Sin token" in app.banner.title_label.text()


def test_the_banner_asks_to_validate_an_unvalidated_token(app):
    app.token_entry.setText("token-value")

    app._refresh_banner()

    assert app.banner.state() == "warn"
    assert "sin validar" in app.banner.title_label.text().lower()


def test_the_banner_is_green_when_the_account_can_emit(app):
    _validated(app)

    app._refresh_banner()

    assert app.banner.state() == "ok"
    assert "Listo" in app.banner.title_label.text()
    assert "@creator" in app.banner.detail_label.text()


def test_the_banner_warns_when_the_account_cannot_emit(app):
    _validated(app)
    app._account_info = AccountInfo("creator", "pending", False)

    app._refresh_banner()

    assert app.banner.state() == "error"
    assert "Sin permiso" in app.banner.title_label.text()


def test_the_banner_announces_a_prepared_stream(app):
    _validated(app)
    app._active_session = StreamSession("session-1", "rtmp://server", "key")
    app._session_record = ActiveSession("session-1", "Title", "2026-01-01T20:15:00+00:00")

    app._refresh_banner()

    assert app.banner.state() == "live"
    assert "Directo preparado" in app.banner.title_label.text()
    assert "desde las" in app.banner.detail_label.text()


def test_the_live_permission_is_never_shown_as_a_python_boolean(app):
    app._set_can_go_live(True)
    assert app.can_go_live.text() == "Sí"
    assert app.can_go_live.property("state") == "ok"

    app._set_can_go_live(False)
    assert app.can_go_live.text() == "No"
    assert app.can_go_live.property("state") == "error"

    app._set_can_go_live(None)
    assert app.can_go_live.text() == "—"


def test_a_validated_account_never_leaves_the_boolean_on_screen(app):
    _validated(app)

    app.tiktok_username.setText("creator")
    app._set_can_go_live(app._account_info.can_be_live)

    assert "True" not in app.can_go_live.text()
    assert app.can_go_live.text() == "Sí"


def test_the_progress_bar_only_spins_while_something_is_running(app):
    assert app.progress.is_busy() is False

    app._set_operation_busy("account", True)
    assert app.progress.is_busy() is True

    app._set_operation_busy("account", False)
    assert app.progress.is_busy() is False


def test_the_account_section_summarises_itself(app):
    _validated(app)

    app._update_controls()
    assert app.account_section.summary_label.text() == "@creator"

    app.handle_token_change()
    assert app.account_section.summary_label.text() == "token sin validar"


def test_the_account_section_starts_folded_when_a_token_is_saved(app, store, qtbot):
    store.save(AppConfig(title="Guardado"))
    window = StreamApp(config_store=store, token_store=app.token_store)
    qtbot.addWidget(window)
    window.token_entry.setText("token-guardado")

    window._finish_startup()

    assert window.account_section.is_expanded() is False


# --------------------------------------------------------------------------- #
#  Copying without a dialog                                                   #
# --------------------------------------------------------------------------- #


def test_copying_confirms_in_the_field_and_opens_no_dialog(app, monkeypatch):
    dialogs = []
    monkeypatch.setattr(
        application.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: dialogs.append(args)),
    )
    app.stream_url.setText("rtmp://push.tiktok.com/live/")

    app.stream_url.copy_button.click()

    assert dialogs == []
    assert app.stream_url.is_confirming() is True
    assert "copiada" in app.app_status.text().lower()


def test_copying_the_key_arms_the_clipboard_cleanup(app):
    app.stream_key.setText("clave-secreta")

    app.stream_key.copy_button.click()

    assert app._clipboard_timer.isActive() is True
    assert app._clipboard_value == "clave-secreta"


def test_an_empty_field_is_not_copied(app, monkeypatch):
    dialogs = []
    monkeypatch.setattr(
        application.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: dialogs.append(args)),
    )

    app.copy_to_clipboard(app.stream_url, False)

    assert dialogs == []
    assert app.stream_url.is_confirming() is False


def test_the_stream_key_can_be_revealed_like_the_token(app):
    assert app.stream_key.is_revealed() is False

    app.stream_key.reveal_button.click()

    assert app.stream_key.is_revealed() is True


# --------------------------------------------------------------------------- #
#  Installing an update                                                       #
# --------------------------------------------------------------------------- #


def test_installing_is_never_offered_while_a_session_is_open(app, monkeypatch):
    from ui import update_flow

    monkeypatch.setattr(update_flow, "can_self_install", lambda system, asset: True)
    asset = {"name": "Setup-app-2.0.0.exe"}

    assert app._can_install_update(asset, "Windows") is True

    app._active_session = StreamSession("session-1", "rtmp://server", "key")

    assert app._can_install_update(asset, "Windows") is False


def test_starting_the_installer_closes_the_application(app, tmp_path, monkeypatch):
    from ui import update_flow

    installer = tmp_path / "Setup-app-2.0.0.exe"
    installer.write_bytes(b"fake installer")
    helper = tmp_path / "helper.cmd"
    launched = []
    closed = []
    monkeypatch.setattr(
        update_flow,
        "write_installer_helper",
        lambda directory, **kwargs: helper,
    )
    monkeypatch.setattr(update_flow, "launch_detached", lambda path: launched.append(path))
    monkeypatch.setattr(app, "close", lambda: closed.append(True))

    app._launch_installer(installer)

    assert launched == [helper]
    assert closed == [True]


def test_a_failed_launch_tells_the_user_where_the_installer_is(app, tmp_path, monkeypatch):
    from ui import update_flow

    installer = tmp_path / "Setup-app-2.0.0.exe"
    installer.write_bytes(b"fake installer")
    warnings = []
    monkeypatch.setattr(
        application.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    def explode(directory, **kwargs):
        raise OSError("no se pudo escribir el ayudante")

    monkeypatch.setattr(update_flow, "write_installer_helper", explode)

    app._launch_installer(installer)

    assert warnings
    # The message has to say where the installer is, so it can be run by hand.
    assert str(installer) in warnings[0][2]
