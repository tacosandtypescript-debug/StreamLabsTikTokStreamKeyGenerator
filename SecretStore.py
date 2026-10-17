"""Protect the Streamlabs token at rest.

Windows uses DPAPI (per-user, per-machine); other platforms keep the historical
plain-text value because the app has no keyring dependency.
"""

import base64
import binascii
import ctypes
import sys
from ctypes import wintypes

PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _win_apis():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _dpapi(data, *, decrypt=False):
    crypt32, kernel32 = _win_apis()
    blob_in = _blob(data)
    blob_out = _DataBlob()
    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI operation failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def is_protected(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(value):
    if not isinstance(value, str) or not value:
        return ""
    if sys.platform != "win32":
        return value
    encrypted = _dpapi(value.encode("utf-8"))
    return PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect(value):
    if not isinstance(value, str) or not value:
        return ""
    if not is_protected(value):
        return value
    if sys.platform != "win32":
        return ""
    try:
        encrypted = base64.b64decode(value[len(PREFIX):], validate=True)
    except (ValueError, binascii.Error):
        return ""
    try:
        return _dpapi(encrypted, decrypt=True).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
