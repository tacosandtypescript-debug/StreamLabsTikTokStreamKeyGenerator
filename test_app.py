import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPushButton, QScrollArea
from Stream import Stream
from TokenRetriever import TokenRetriever
from SecretStore import unprotect
from StreamLabsTikTokStreamKeyGenerator import StreamApp
from test_stream import response
from unittest.mock import Mock
import requests


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.real_save = StreamApp.save_config
        cls.real_load = StreamApp.load_config

    def setUp(self):
        self.patches = [patch.object(StreamApp, "load_config"), patch.object(StreamApp, "save_config", return_value=True)]
        for item in self.patches:
            item.start()
        self.config_dir = tempfile.TemporaryDirectory()
        self.window = StreamApp(startup_checks=False, config_path=os.path.join(self.config_dir.name, 'config.json'))
        self.client = Stream("unit-account-token")
        self.client.s = Mock()
        self.window.stream = self.client
        self.window._client_token = "unit-account-token"
        self.window.token_entry.setText("unit-account-token")
        self.window._can_go_live = True
        self.window.stream_title.setText("Test")
        self.window.game_category.blockSignals(True)
        self.window.game_category.setText("Other")
        self.window.game_category.blockSignals(False)
        self.window._categories = {"Other": ""}
        self.window._sync_controls()

    def tearDown(self):
        self.window._search_timer.stop()
        self.window._api_busy = False
        self.window.stream = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.config_dir.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "GUI operation timed out")

    def start_prepared(self):
        self.client.s.post.return_value = response(payload={"id": "session-1", "rtmp": "rtmps://example.invalid/app", "key": "unit-key"})
        self.window.start_stream()
        self.wait_for(lambda: not self.window._api_busy)

    def test_small_window_scrolls_instead_of_clipping_content(self):
        self.window.resize(800, 600)
        self.window.show()
        self.app.processEvents()
        self.window.login_status.setText(
            "Se agotó el tiempo de inicio de sesión. Puedes reintentar. No hay ninguna cuenta cargada."
        )
        self.window.suggestions_list.addItems(["Categoría uno", "Categoría dos"])
        self.window.suggestions_list.setVisible(True)
        self.app.processEvents()
        scroll = self.window.centralWidget()
        self.assertIsInstance(scroll, QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)

    def test_token_is_queued_while_api_is_busy(self):
        self.window._api_busy = True
        self.window._apply_token("queued-token", success_message="Inicio de sesión completado.")
        self.assertEqual(self.window.token_entry.text(), "unit-account-token")
        self.assertIn("Se aplicará", self.window.login_status.text())
        with patch.object(self.window, "refresh_account_info"):
            self.window._api_busy = False
            self.window._finish_api((self.client, "info", {"can_be_live": True}, ""))
        self.assertEqual(self.window.token_entry.text(), "queued-token")
        self.assertIsNone(self.window._pending_token)

    def test_online_cancel_restores_retry_and_ignores_stale_completion(self):
        first = TokenRetriever()
        self.window._online_retriever = first
        self.window._sync_controls()
        self.assertTrue(self.window.cancel_login_btn.isEnabled())
        self.assertFalse(self.window.load_online_btn.isEnabled())
        self.window.cancel_login_btn.click()
        self.assertTrue(first.cancelled.is_set())
        self.assertTrue(self.window.load_online_btn.isEnabled())
        second = TokenRetriever()
        self.window._online_retriever = second
        self.window._sync_controls()
        self.window._finish_online_token((first, 'stale-token'))
        self.assertIs(self.window._online_retriever, second)
        self.assertEqual(self.window.token_entry.text(), 'unit-account-token')
        self.window.cancel_online_login()

    def test_interface_is_spanish_and_has_no_donation_controls(self):
        button_texts = [button.text() for button in self.window.findChildren(QPushButton)]
        self.assertNotIn("Donate", " ".join(button_texts))
        self.assertFalse(hasattr(self.window, "donate_btn"))
        self.assertFalse(hasattr(self.window, "suppress_donation_reminder"))
        self.assertFalse(any(
            any(0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF for char in text)
            for text in button_texts
        ))
        self.assertEqual(self.window.load_local_btn.text(), "Cargar desde el PC")
        self.assertEqual(self.window.load_online_btn.text(), "Cargar desde la web")
        self.assertEqual(self.window.change_account_btn.text(), "Cambiar cuenta")
        self.assertEqual(self.window.go_live_btn.text(), "Preparar transmisión")
        self.assertEqual(self.window.end_live_btn.text(), "Finalizar transmisión")
        self.assertEqual(self.window.save_btn.text(), "Guardar configuración")
        self.assertEqual(self.window.help_btn.text(), "Ayuda")
        self.assertEqual(self.window.brand_name.text(), "FPV Stream")
        self.assertFalse(self.window.windowIcon().isNull())
        self.assertIn("#DF2531", self.window.styleSheet())
        self.assertEqual(self.window.toggle_token_btn.text(), "Ver")
        self.window.toggle_token_visibility()
        self.assertEqual(self.window.toggle_token_btn.text(), "Ocultar")

    def test_update_check_runs_off_the_gui_thread(self):
        calls = []
        def fake_check():
            calls.append(threading.get_ident())
            return None
        with patch('StreamLabsTikTokStreamKeyGenerator.VersionChecker.check_update', side_effect=fake_check):
            self.window.check_updates_on_startup()
            self.wait_for(lambda: bool(calls))
        self.assertNotEqual(calls[0], threading.get_ident())

    def test_update_dialog_is_only_shown_for_a_newer_version(self):
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.No) as dialog:
            self.window._show_update({'latest': '2.0.8', 'current': '2.0.9', 'url': 'https://example.invalid'})
        dialog.assert_not_called()
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.No) as dialog, \
             patch('StreamLabsTikTokStreamKeyGenerator.QDesktopServices.openUrl') as open_url:
            self.window._show_update({'latest': '2.0.10', 'current': '2.0.9', 'url': 'https://example.invalid'})
        dialog.assert_called_once()
        open_url.assert_not_called()

    def test_failed_browser_launch_returns_to_retry(self):
        with patch('StreamLabsTikTokStreamKeyGenerator.open_browser', return_value=False), \
             patch('StreamLabsTikTokStreamKeyGenerator.QDesktopServices.openUrl', return_value=False):
            self.window.fetch_online_token()
            self.wait_for(lambda: self.window._online_retriever is None)
        self.assertTrue(self.window.load_online_btn.isEnabled())
        self.assertFalse(self.window.cancel_login_btn.isEnabled())
        self.assertIn('navegador', self.window.login_status.text())

    def test_browser_launch_falls_back_to_qt_url_handler(self):
        with patch('StreamLabsTikTokStreamKeyGenerator.open_browser', return_value=False), \
             patch('StreamLabsTikTokStreamKeyGenerator.QDesktopServices.openUrl', return_value=True) as fallback:
            self.window.fetch_online_token()
            retriever = self.window._online_retriever
            self.wait_for(lambda: fallback.called)
            self.window.cancel_login_btn.click()
            self.wait_for(lambda: retriever.cancelled.is_set())
        fallback.assert_called_once()
        self.assertIn('https://streamlabs.com/slobs/login?', fallback.call_args.args[0].toString())

    def test_browser_opens_with_default_browser_and_cancel_does_not_reopen(self):
        calls = []
        gui_thread = threading.get_ident()
        def opened(url):
            calls.append((threading.get_ident() != gui_thread, url))
            return True
        with patch('StreamLabsTikTokStreamKeyGenerator.open_browser', side_effect=opened), \
             patch('StreamLabsTikTokStreamKeyGenerator.QDesktopServices.openUrl') as qt_fallback:
            self.window.fetch_online_token()
            retriever = self.window._online_retriever
            self.wait_for(lambda: bool(calls))
            self.window.cancel_login_btn.click()
            self.wait_for(lambda: retriever.cancelled.is_set())
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0])
        self.assertIn('prompt=login', calls[0][1])
        qt_fallback.assert_not_called()
        self.assertTrue(self.window.load_online_btn.isEnabled())

    def test_prepared_does_not_claim_received_video(self):
        self.start_prepared()
        self.assertEqual(self.window.live_state, "prepared")
        self.assertNotIn("EN VIVO", self.window.live_status.text())
        self.assertIn("sin confirmar", self.window.video_status.text())
        self.assertTrue(self.window.end_live_btn.isEnabled())
        self.assertFalse(self.window.go_live_btn.isEnabled())
        self.assertEqual(self.window.stream_key.echoMode(), QLineEdit.Password)

    def test_start_is_async_and_double_click_does_not_duplicate(self):
        release = threading.Event()
        self.client.s.post.side_effect = lambda *a, **k: (release.wait(2), response(payload={"id": "session-1", "rtmp": "rtmps://example.invalid/app", "key": "unit-key"}))[1]
        ticks = []
        try:
            self.window.start_stream()
            self.window.start_stream()
            QTimer.singleShot(0, lambda: ticks.append(1))
            self.wait_for(lambda: bool(ticks) and self.client.s.post.call_count == 1)
            self.assertTrue(self.window._api_busy)
            self.assertFalse(self.window.go_live_btn.isEnabled())
        finally:
            release.set()
            self.wait_for(lambda: not self.window._api_busy)

    def test_refresh_preserves_session_client_and_end_action(self):
        self.start_prepared()
        self.client.s.get.return_value = response(payload={"can_be_live": True})
        self.window.refresh_account_info()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertIs(self.window.stream, self.client)
        self.assertEqual(self.client.id, "session-1")
        self.assertFalse(self.window.go_live_btn.isEnabled())
        self.assertTrue(self.window.end_live_btn.isEnabled())

    def test_end_timeout_keeps_session_and_no_new_start(self):
        self.start_prepared()
        self.client.s.post.side_effect = requests.Timeout()
        self.window.end_stream()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.client.id, "session-1")
        self.assertEqual(self.window.live_state, "uncertain")
        self.assertTrue(self.window.end_live_btn.isEnabled())
        self.assertFalse(self.window.copy_key_btn.isEnabled())
        count = self.client.s.post.call_count
        self.window.start_stream()
        self.assertEqual(self.client.s.post.call_count, count)

    def test_end_confirmed_clears_credentials_and_unlocks(self):
        self.start_prepared()
        self.client.s.post.return_value = response(payload={"success": True})
        self.window.end_stream()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.window.live_state, "offline")
        self.assertFalse(self.window.stream_key.text())
        self.assertTrue(self.window.go_live_btn.isEnabled())

    def test_account_change_does_not_discard_session(self):
        self.start_prepared()
        self.window.token_entry.setText("other-unit-account")
        self.window.refresh_account_info()
        self.assertIs(self.window.stream, self.client)
        self.assertEqual(self.client.id, "session-1")
        self.assertEqual(self.window.token_entry.text(), "unit-account-token")

    def test_change_account_erases_saved_identity_before_opening_login(self):
        self.window.tiktok_username.setText('previous-user')
        self.window.app_status.setText('approved')
        self.window.stream_url.setText('rtmps://example.invalid/previous')
        self.window.stream_key.setText('previous-key')
        self.window._saved_session = {'id': 'stale-session'}

        def verify_cleared_before_launch():
            with open(self.window.config_path) as file:
                saved = json.load(file)
            self.assertEqual(saved['token'], '')
            self.assertNotIn('session', saved)
            self.assertIsNone(self.window.stream)
            self.assertEqual(self.window._client_token, '')
            self.assertFalse(self.window.tiktok_username.text())
            self.assertFalse(self.window.app_status.text())
            self.assertFalse(self.window.can_go_live.text())
            self.assertFalse(self.window.stream_key.text())
            self.assertFalse(self.window.stream_url.text())
            self.assertIsNone(self.window._saved_session)

        with patch.object(self.window, 'save_config', side_effect=lambda show, data=None: type(self).real_save(self.window, show, data)), \
             patch.object(self.window, 'fetch_online_token', side_effect=verify_cleared_before_launch) as launch:
            self.window.change_account_btn.click()
        launch.assert_called_once()
        self.assertFalse(self.window.go_live_btn.isEnabled())
        self.assertEqual(self.window.stream_title.text(), 'Test')
        restarted = StreamApp(startup_checks=False, config_path=self.window.config_path)
        try:
            type(self).real_load(restarted)
            self.assertFalse(restarted.token_entry.text())
            self.assertIsNone(restarted.stream)
            self.assertFalse(restarted.tiktok_username.text())
            self.assertFalse(restarted.change_account_btn.isEnabled())
        finally:
            restarted.close()
            restarted.deleteLater()

    def test_change_account_discards_late_account_and_local_results(self):
        old_generation = self.window._account_generation
        old_login = TokenRetriever()
        self.window._online_retriever = old_login
        self.window._api_busy = True
        self.window._pending_operation = 'info'
        with patch.object(self.window, 'fetch_online_token'):
            self.window.change_account()
        self.window._finish_api((self.client, 'info', {'user': {'username': 'previous-user'}, 'can_be_live': True}, ''))
        self.window._apply_local_token((old_generation, 'stale-local-token'))
        self.window._finish_online_token((old_login, 'stale-web-token'))
        self.window._finish_search((self.client, old_generation, 'Other', [{'full_name': 'Old', 'game_mask_id': 'old'}], ''))
        self.assertTrue(old_login.cancelled.is_set())
        self.assertFalse(self.window.token_entry.text())
        self.assertFalse(self.window.tiktok_username.text())
        self.assertIsNone(self.window.stream)
        self.assertFalse(self.window._api_busy)
        self.assertFalse(self.window._categories)

    def test_change_account_cancel_keeps_previous_account_removed(self):
        with patch('StreamLabsTikTokStreamKeyGenerator.open_browser', return_value=True), \
             patch.object(self.window, 'save_config', side_effect=lambda show, data=None: type(self).real_save(self.window, show, data)):
            self.window.change_account_btn.click()
            retriever = self.window._online_retriever
            self.window.cancel_login_btn.click()
            self.wait_for(lambda: retriever.cancelled.is_set())
        with open(self.window.config_path) as file:
            self.assertEqual(json.load(file)['token'], '')
        self.assertIsNone(self.window.stream)
        self.assertFalse(self.window.token_entry.text())
        self.assertIn('ninguna cuenta', self.window.login_status.text())

    def test_change_account_loads_only_the_new_account(self):
        new_client = Stream('new-unit-token')
        new_client.s = Mock()
        new_client.s.get.return_value = response(payload={
            'user': {'username': 'new-user'}, 'application_status': {'status': 'approved'}, 'can_be_live': True
        })
        with patch('StreamLabsTikTokStreamKeyGenerator.TokenRetriever.retrieve_token', return_value='new-unit-token'), \
             patch('StreamLabsTikTokStreamKeyGenerator.Stream', return_value=new_client), \
             patch.object(self.window, 'save_config', side_effect=lambda show, data=None: type(self).real_save(self.window, show, data)):
            self.window.change_account_btn.click()
            self.wait_for(lambda: self.window.tiktok_username.text() == 'new-user' and not self.window._api_busy)
        self.assertIs(self.window.stream, new_client)
        self.assertEqual(self.window.token_entry.text(), 'new-unit-token')
        with open(self.window.config_path) as file:
            self.assertEqual(unprotect(json.load(file)['token']), 'new-unit-token')
        self.assertTrue(self.window.go_live_btn.isEnabled())

    def test_change_account_preserves_prepared_session_and_explains_block(self):
        self.start_prepared()
        with patch.object(self.window, 'fetch_online_token') as launch:
            self.window.change_account_btn.click()
        launch.assert_not_called()
        self.assertIs(self.window.stream, self.client)
        self.assertEqual(self.client.id, 'session-1')
        self.assertTrue(self.window.stream_key.text())
        self.assertIn('Finaliza', self.window.login_status.text())

    def test_change_account_save_failure_blocks_login_and_allows_retry(self):
        with patch.object(self.window, 'save_config', return_value=False), \
             patch.object(self.window, 'fetch_online_token') as launch:
            self.window.change_account_btn.click()
        launch.assert_not_called()
        self.assertTrue(self.window.change_account_btn.isEnabled())
        self.assertIn('No se pudo borrar', self.window.login_status.text())
        self.assertEqual(self.window.token_entry.text(), 'unit-account-token')
        self.assertIs(self.window.stream, self.client)
        with patch('StreamLabsTikTokStreamKeyGenerator.TokenRetriever') as retriever:
            self.window.fetch_online_token()
        retriever.assert_not_called()

    def test_manual_close_requires_explicit_confirmation(self):
        self.client.id = "session-1"
        self.client.session_uncertain = True
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.window.confirm_manual_close()
        self.assertEqual(self.client.id, "session-1")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.window.confirm_manual_close()
        self.assertIsNone(self.client.id)
        self.assertFalse(self.client.session_uncertain)
        self.client.s.post.assert_not_called()

    def test_pending_session_is_saved_without_publication_key(self):
        self.window._api_busy = True
        self.window._pending_operation = "start"
        self.window.stream_key.setText("UNIT-SECRET-NOT-TO-PERSIST")
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as unrelated_folder:
            try:
                os.chdir(unrelated_folder)
                self.assertTrue(type(self).real_save(self.window, False))
                self.assertFalse(os.path.exists('config.json'))
            finally:
                os.chdir(previous)
        with open(self.window.config_path) as file:
            saved = json.load(file)
        self.assertTrue(saved["session"]["uncertain"])
        self.assertEqual(saved["session"]["account"], hashlib.sha256(b"unit-account-token").hexdigest())
        self.assertNotIn("UNIT-SECRET-NOT-TO-PERSIST", json.dumps(saved))
        self.assertNotIn("suppress_donation_reminder", saved)

    def test_worker_exception_is_safe_and_uncertain(self):
        self.client.start = Mock(side_effect=RuntimeError("UNIT-SECRET"))
        self.window.start_stream()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.window.live_state, "uncertain")
        self.assertNotIn("UNIT-SECRET", self.window.live_status.text())

    def test_copied_key_is_cleared_from_the_clipboard(self):
        self.window.CLIPBOARD_CLEAR_MS = 0
        self.window.stream_key.setText('secret-key')
        with patch.object(QMessageBox, 'information'):
            self.window.copy_to_clipboard(self.window.stream_key)
        self.assertEqual(QApplication.clipboard().text(), 'secret-key')
        QTest.qWait(50)
        self.assertEqual(QApplication.clipboard().text(), '')

    def test_unrelated_clipboard_content_is_preserved(self):
        self.window.CLIPBOARD_CLEAR_MS = 0
        self.window.stream_key.setText('secret-key')
        with patch.object(QMessageBox, 'information'):
            self.window.copy_to_clipboard(self.window.stream_key)
        QApplication.clipboard().setText('other content')
        QTest.qWait(50)
        self.assertEqual(QApplication.clipboard().text(), 'other content')

    def test_stale_search_result_releases_inflight_flag(self):
        self.window._search_inflight = True
        self.window._finish_search((Stream("other-account"), self.window._search_generation, "Old", [], ""))
        self.assertFalse(self.window._search_inflight)

    def test_stale_category_result_is_ignored(self):
        self.window.game_category.setText("Newest")
        self.window._search_generation = 10
        self.window._finish_search((self.client, 9, "Old", [{"full_name": "Old", "game_mask_id": "1"}], ""))
        self.assertNotIn("Old", self.window._categories)
        self.window._search_timer.stop()

    def test_key_visibility_is_explicit_and_rehidden_on_clear(self):
        self.start_prepared()
        self.window.toggle_key_visibility()
        self.assertEqual(self.window.stream_key.echoMode(), QLineEdit.Normal)
        self.window._clear_credentials()
        self.assertEqual(self.window.stream_key.echoMode(), QLineEdit.Password)

    def test_failed_journal_write_prevents_external_start(self):
        with patch.object(self.window, "save_config", return_value=False):
            self.window.start_stream()
        self.client.s.post.assert_not_called()
        self.assertFalse(self.window._api_busy)
        self.assertIn("no se envió", self.window.live_status.text())

    def test_restore_retains_session_but_never_claims_signal(self):
        self.window.stream = None
        self.window._client_token = ""
        self.window._saved_session = {"id": "restored", "uncertain": False,
            "account": hashlib.sha256(b"unit-account-token").hexdigest()}
        self.client.s.get.return_value = response(payload={"can_be_live": True})
        with patch("StreamLabsTikTokStreamKeyGenerator.Stream", return_value=self.client):
            self.window.refresh_account_info()
            self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.client.id, "restored")
        self.assertTrue(self.client.session_uncertain)
        self.assertFalse(self.window.go_live_btn.isEnabled())
        self.assertIn("sin confirmar", self.window.video_status.text())

    def test_refresh_auth_error_retains_endable_session(self):
        self.start_prepared()
        self.client.s.get.return_value = response(401, {})
        self.window.refresh_account_info()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.client.id, "session-1")
        self.assertTrue(self.window.end_live_btn.isEnabled())
        self.assertIn("401", self.window.app_status.text())

    def test_empty_title_never_dispatches_start(self):
        self.window.stream_title.clear()
        self.window.start_stream()
        self.client.s.post.assert_not_called()
        self.assertIn("título", self.window.live_status.text())


if __name__ == "__main__":
    unittest.main()
