import subprocess
import sys
import unittest
from unittest.mock import patch

from BrowserLauncher import open_browser

URL = "https://streamlabs.com/slobs/login?port=12345&code_challenge=test&code_flow=true"
BROWSER = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class BrowserLauncherTests(unittest.TestCase):
    def test_system_handler_opens_the_url_first(self):
        with patch("BrowserLauncher.webbrowser.open", return_value=True) as shell_open, \
             patch("BrowserLauncher._launch_visible_window") as visible:
            self.assertTrue(open_browser(URL))
        shell_open.assert_called_once_with(URL, new=2)
        visible.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows browser integration')
    def test_visible_window_fallback_preserves_oauth_query(self):
        with patch("BrowserLauncher.webbrowser.open", return_value=False), \
             patch("BrowserLauncher._windows_browser_executable", return_value=BROWSER), \
             patch("BrowserLauncher.subprocess.Popen") as launch:
            launch.return_value.wait.return_value = 0
            self.assertTrue(open_browser(URL))
        self.assertEqual(launch.call_args.args[0], [BROWSER, '--new-window', URL])
        startup = launch.call_args.kwargs['startupinfo']
        self.assertTrue(startup.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startup.wShowWindow, 1)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows browser integration')
    def test_failed_visible_launch_is_not_reported_as_success(self):
        with patch("BrowserLauncher.webbrowser.open", return_value=False), \
             patch("BrowserLauncher._windows_browser_executable", return_value=BROWSER), \
             patch("BrowserLauncher.subprocess.Popen") as launch:
            launch.return_value.wait.return_value = 5
            self.assertFalse(open_browser(URL))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows browser integration')
    def test_missing_browser_or_failed_process_is_reported(self):
        for executable in (None, r'C:\missing\chrome.exe'):
            with self.subTest(executable=executable), \
                 patch("BrowserLauncher.webbrowser.open", return_value=False), \
                 patch("BrowserLauncher._windows_browser_executable", return_value=executable), \
                 patch("BrowserLauncher.subprocess.Popen", side_effect=OSError):
                self.assertFalse(open_browser(URL))

    def test_launcher_errors_are_reported_as_failure(self):
        with patch("BrowserLauncher.webbrowser.open", side_effect=OSError), \
             patch("BrowserLauncher._launch_visible_window", return_value=False):
            self.assertFalse(open_browser(URL))
