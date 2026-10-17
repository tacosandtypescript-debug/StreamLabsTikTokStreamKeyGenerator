"""Open the login URL in the user's browser."""

import ntpath
import os
import re
import subprocess
import sys
import webbrowser


def _windows_browser_executable():
    import winreg

    try:
        choice_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, choice_path) as key:
            program_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, program_id + r"\shell\open\command") as key:
            command = winreg.QueryValue(key, None)
        match = re.match(r'^\s*"([^"]+)"', command) or re.match(r"^\s*(.*?\.exe)(?:\s|$)", command, re.I)
        if not match:
            return None
        executable = os.path.expandvars(match.group(1))
        if ntpath.basename(executable).lower() not in {"chrome.exe", "msedge.exe", "firefox.exe"}:
            return None
        return executable if os.path.isfile(executable) else None
    except (OSError, ValueError, TypeError):
        return None


def _launch_visible_window(url):
    executable = _windows_browser_executable()
    if not executable:
        return False
    try:
        # Request a visible new window explicitly, without executing the
        # registry command through a shell or splitting the OAuth query.
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1  # SW_SHOWNORMAL
        process = subprocess.Popen([executable, "--new-window", url], startupinfo=startup)
    except OSError:
        return False
    try:
        # A running browser hands the URL over and exits successfully. A
        # non-zero exit means the visible window never started (for example,
        # a restricted token that cannot open the browser profile).
        return process.wait(timeout=2) == 0
    except subprocess.TimeoutExpired:
        return True


def open_browser(url):
    """Open the URL with the system handler, falling back to a known browser.

    The system handler is the path that already works on the user's desktop and
    stays valid even when the registered browser executable is unusual. The
    explicit visible-window request is only a fallback for when the handler
    reports that it could not dispatch the URL.
    """
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    if sys.platform == "win32":
        return _launch_visible_window(url)
    return False
