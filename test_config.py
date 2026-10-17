import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from StreamLabsTikTokStreamKeyGenerator import StreamApp


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def open_app(self, payload):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "config.json")
        if payload is not None:
            with open(self.path, "w", encoding="utf-8") as file:
                file.write(payload if isinstance(payload, str) else json.dumps(payload))
        with patch.object(StreamApp, "refresh_account_info"), \
             patch.object(StreamApp, "save_config", return_value=True):
            window = StreamApp(startup_checks=False, config_path=self.path)
        self.addCleanup(self.close_window, window)
        return window

    def close_window(self, window):
        window._search_timer.stop()
        window.stream = None
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_missing_config_uses_defaults(self):
        window = self.open_app(None)
        self.assertEqual(window.token_entry.text(), "")
        self.assertEqual(window.stream_title.text(), "")
        self.assertFalse(window.mature_checkbox.isChecked())
        self.assertFalse(os.path.exists(self.path + ".bak"))

    def test_corrupt_config_is_quarantined_and_app_starts(self):
        for payload in ("[]", "{bad json", "null"):
            with self.subTest(payload=payload):
                window = self.open_app(payload)
                self.assertEqual(window.token_entry.text(), "")
                self.assertEqual(window.stream_title.text(), "")
                self.assertTrue(os.path.exists(self.path + ".bak"))
                self.assertIn("dañada", window.live_status.text())

    def test_invalid_field_types_are_quarantined(self):
        window = self.open_app({"token": 123, "title": ["bad"], "session": "nope"})
        self.assertEqual(window.token_entry.text(), "")
        self.assertEqual(window.stream_title.text(), "")
        self.assertIsNone(window._saved_session)
        self.assertTrue(os.path.exists(self.path + ".bak"))

    def test_valid_config_is_loaded(self):
        session = {"id": "session-1", "uncertain": False, "account": "hash"}
        window = self.open_app({
            "token": "unit-token",
            "title": "Prueba",
            "game": "Gaming",
            "audience_type": "1",
            "session": session,
        })
        self.assertEqual(window.token_entry.text(), "unit-token")
        self.assertEqual(window.stream_title.text(), "Prueba")
        self.assertEqual(window.game_category.text(), "Gaming")
        self.assertTrue(window.mature_checkbox.isChecked())
        self.assertEqual(window._saved_session, session)
        self.assertFalse(os.path.exists(self.path + ".bak"))


if __name__ == "__main__":
    unittest.main()
