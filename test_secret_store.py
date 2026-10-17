import sys
import unittest

from SecretStore import is_protected, protect, unprotect


class SecretStoreTests(unittest.TestCase):
    def test_empty_values_stay_empty(self):
        self.assertEqual(protect(""), "")
        self.assertEqual(unprotect(""), "")

    def test_legacy_plain_text_is_accepted(self):
        self.assertEqual(unprotect("legacy-token"), "legacy-token")
        self.assertFalse(is_protected("legacy-token"))

    def test_invalid_protected_value_is_rejected(self):
        self.assertEqual(unprotect("dpapi:not-base64!"), "")

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_windows_protects_and_unprotects_the_token(self):
        token = "unit-test-token-0123456789"
        protected = protect(token)
        self.assertTrue(is_protected(protected))
        self.assertNotIn(token, protected)
        self.assertEqual(unprotect(protected), token)

    @unittest.skipUnless(sys.platform != "win32", "non-Windows fallback")
    def test_other_platforms_keep_the_historical_plain_value(self):
        self.assertEqual(protect("token"), "token")


if __name__ == "__main__":
    unittest.main()
