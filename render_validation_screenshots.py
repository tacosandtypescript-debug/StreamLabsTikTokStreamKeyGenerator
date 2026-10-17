"""Render the validation screenshots offscreen with synthetic credentials.

Usage: .venv/Scripts/python.exe render_validation_screenshots.py
Never contacts Streamlabs: config loading and saving are stubbed out.
"""

import os
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    # The offscreen platform plugin does not read the system font database in
    # this PySide6 build; point it at the installed Windows fonts instead.
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Stream import Stream
from StreamLabsTikTokStreamKeyGenerator import StreamApp
from TokenRetriever import TokenRetriever

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "docs", "validation")
TOKEN = "synthetic-demo-token"
KEY = "synthetic-demo-stream-key"


def make_window(app):
    config_dir = tempfile.TemporaryDirectory()
    stack = [
        patch.object(StreamApp, "load_config"),
        patch.object(StreamApp, "save_config", return_value=True),
        patch.object(StreamApp, "fetch_game_mask_id"),
    ]
    for item in stack:
        item.start()
    window = StreamApp(startup_checks=False, config_path=os.path.join(config_dir.name, "config.json"))
    return window, config_dir, stack


def with_account(window, username="fpv_stream_demo"):
    client = Stream(TOKEN)
    client.s = None  # no network calls are made while rendering
    window.stream = client
    window._client_token = TOKEN
    window.token_entry.setText(TOKEN)
    window.tiktok_username.setText(username)
    window.app_status.setText("approved")
    window.can_go_live.setText("Sí")
    window._can_go_live = True
    return client


def render(app, window, name, size):
    window.resize(*size)
    window.show()
    app.processEvents()
    QTest.qWait(80)
    app.processEvents()
    path = os.path.join(OUTPUT, name)
    assert window.grab().save(path, "PNG"), path
    window.hide()
    app.processEvents()
    print(f"{name}: {size[0]}x{size[1]}")


def prepare_shot(app):
    window, config_dir, stack = make_window(app)
    with_account(window)
    window.stream.id = "synthetic-session"
    window.stream_title.setText("Prueba de directo FPV")
    window.game_category.setText("Gaming")
    window._categories = {"Gaming": "10203"}
    window.game_mask_id = "10203"
    window.stream_url.setText("rtmps://example.invalid/app")
    window.stream_key.setText(KEY)
    window._set_live_state("prepared")
    try:
        render(app, window, "generator-prepared.png", (1000, 760))
    finally:
        cleanup(window, config_dir, stack)


def uncertain_shot(app):
    window, config_dir, stack = make_window(app)
    client = with_account(window)
    client.session_uncertain = True
    window.stream_title.setText("Prueba de directo FPV")
    window.game_category.setText("Gaming")
    window._set_live_state(
        "uncertain",
        "No se confirmó el cierre. Revisa Live Monitor o vuelve a intentar finalizar la transmisión.",
    )
    try:
        render(app, window, "generator-uncertain.png", (800, 600))
    finally:
        cleanup(window, config_dir, stack)


def login_shot(app):
    window, config_dir, stack = make_window(app)
    retriever = TokenRetriever()
    window._online_retriever = retriever
    window.login_status.setText("Abriendo el inicio de sesión de TikTok. Puedes pulsar Cancelar para reintentar.")
    window.stream_title.setText("Prueba de directo FPV")
    window.game_category.setText("Gaming")
    window._set_live_state("offline")
    try:
        render(app, window, "generator-login.png", (800, 600))
    finally:
        retriever.cancel()
        window._online_retriever = None
        cleanup(window, config_dir, stack)


def cleanup(window, config_dir, stack):
    # Dropping the synthetic session keeps closeEvent from asking about it.
    window.stream = None
    window._api_busy = False
    window.close()
    window.deleteLater()
    QApplication.instance().processEvents()
    for item in reversed(stack):
        item.stop()
    config_dir.cleanup()


def main():
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
    os.makedirs(OUTPUT, exist_ok=True)
    prepare_shot(app)
    uncertain_shot(app)
    login_shot(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
