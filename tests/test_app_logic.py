"""GUI logic tests.

These run the real widgets offscreen (``QT_QPA_PLATFORM=offscreen`` in CI) and
avoid every modal dialog and network call, so they stay fast and deterministic.
"""

import pytest
from PySide6.QtGui import QCloseEvent

from config_store import ActiveSession, AppConfig, ConfigStore, read_config_file
from secure_store import ACCOUNT_NAME, SERVICE_NAME, SecureTokenStore
from streamlabs_client import AccountInfo, StreamlabsError, StreamSession
from ui import main_window as application


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
