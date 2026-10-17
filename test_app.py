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
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
from Stream import Stream
from TokenRetriever import TokenRetriever
from StreamLabsTikTokStreamKeyGenerator import StreamApp
from test_stream import response
from unittest.mock import Mock
import requests


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.real_save = StreamApp.save_config

    def setUp(self):
        self.patches = [patch.object(StreamApp, "load_config"), patch.object(StreamApp, "save_config", return_value=True)]
        for item in self.patches:
            item.start()
        self.window = StreamApp(startup_checks=False)
        self.window.suppress_donation_reminder = True
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

    def test_failed_browser_launch_returns_to_retry(self):
        with patch('TokenRetriever.webbrowser.open', return_value=False):
            self.window.fetch_online_token()
            self.wait_for(lambda: self.window._online_retriever is None)
        self.assertTrue(self.window.load_online_btn.isEnabled())
        self.assertFalse(self.window.cancel_login_btn.isEnabled())
        self.assertIn('navegador', self.window.login_status.text())

    def test_original_browser_opens_off_gui_thread_and_cancel_does_not_reopen(self):
        calls = []
        gui_thread = threading.get_ident()
        def opened(url):
            calls.append(threading.get_ident() != gui_thread)
            return True
        with patch('TokenRetriever.webbrowser.open', side_effect=opened):
            self.window.fetch_online_token()
            retriever = self.window._online_retriever
            self.wait_for(lambda: bool(calls))
            self.window.cancel_login_btn.click()
            self.wait_for(lambda: retriever.cancelled.is_set())
        self.assertEqual(calls, [True])
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
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.assertTrue(type(self).real_save(self.window, False))
                with open("config.json") as file:
                    saved = json.load(file)
                self.assertTrue(saved["session"]["uncertain"])
                self.assertEqual(saved["session"]["account"], hashlib.sha256(b"unit-account-token").hexdigest())
                self.assertNotIn("UNIT-SECRET-NOT-TO-PERSIST", json.dumps(saved))
            finally:
                os.chdir(previous)

    def test_worker_exception_is_safe_and_uncertain(self):
        self.client.start = Mock(side_effect=RuntimeError("UNIT-SECRET"))
        self.window.start_stream()
        self.wait_for(lambda: not self.window._api_busy)
        self.assertEqual(self.window.live_state, "uncertain")
        self.assertNotIn("UNIT-SECRET", self.window.live_status.text())

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
