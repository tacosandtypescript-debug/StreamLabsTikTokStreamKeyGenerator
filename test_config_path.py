import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

import StreamLabsTikTokStreamKeyGenerator as app_module
from StreamLabsTikTokStreamKeyGenerator import StreamApp


class ConfigPathTests(unittest.TestCase):
    def test_prefers_the_application_folder_when_writable(self):
        with tempfile.TemporaryDirectory() as app_dir, \
             patch.object(app_module, "APP_DIR", app_dir), \
             patch.object(app_module, "_app_dir_is_writable", return_value=True):
            self.assertEqual(
                app_module.default_config_path(),
                os.path.join(app_dir, "config.json"),
            )

    def test_falls_back_to_user_config_and_migrates_legacy_file(self):
        with tempfile.TemporaryDirectory() as app_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             patch.object(app_module, "APP_DIR", app_dir), \
             patch.object(app_module, "_app_dir_is_writable", return_value=False), \
             patch.object(app_module, "_user_config_dir", return_value=user_dir):
            with open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8") as file:
                json.dump({"token": "legacy"}, file)
            path = app_module.default_config_path()
            self.assertEqual(path, os.path.join(user_dir, "config.json"))
            with open(path, encoding="utf-8") as file:
                self.assertEqual(json.load(file)["token"], "legacy")

    def test_existing_user_config_is_not_overwritten_by_migration(self):
        with tempfile.TemporaryDirectory() as app_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             patch.object(app_module, "APP_DIR", app_dir), \
             patch.object(app_module, "_app_dir_is_writable", return_value=False), \
             patch.object(app_module, "_user_config_dir", return_value=user_dir):
            with open(os.path.join(app_dir, "config.json"), "w", encoding="utf-8") as file:
                json.dump({"token": "legacy"}, file)
            with open(os.path.join(user_dir, "config.json"), "w", encoding="utf-8") as file:
                json.dump({"token": "current"}, file)
            app_module.default_config_path()
            with open(os.path.join(user_dir, "config.json"), encoding="utf-8") as file:
                self.assertEqual(json.load(file)["token"], "current")


class ConfigWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_creates_the_missing_config_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "nested", "config.json")
            with patch.object(StreamApp, "load_config"):
                window = StreamApp(startup_checks=False, config_path=config_path)
            try:
                self.assertTrue(window.save_config(False))
                self.assertTrue(os.path.exists(config_path))
                with open(config_path, encoding="utf-8") as file:
                    self.assertEqual(json.load(file)["token"], "")
            finally:
                window._search_timer.stop()
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
