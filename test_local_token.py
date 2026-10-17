import os
import tempfile
import unittest
from unittest.mock import patch

from StreamLabsTikTokStreamKeyGenerator import local_token_files, token_from_file


class LocalTokenTests(unittest.TestCase):
    def test_reads_a_token_split_across_small_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.log")
            with open(path, "wb") as file:
                file.write(b'prefix\x00"apiToken":"abcdef0123456789"\x00suffix')
            self.assertEqual(token_from_file(path, chunk_size=5), "abcdef0123456789")

    def test_keeps_the_last_token_in_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.log")
            with open(path, "wb") as file:
                file.write(b'"apiToken":"aaaa" "apiToken":"bbbb"')
            self.assertEqual(token_from_file(path), "bbbb")

    def test_windows_scan_includes_log_and_ldb_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("a.log", "b.ldb", "ignored.txt"):
                with open(os.path.join(directory, name), "wb") as file:
                    file.write(b"x")
            with patch("StreamLabsTikTokStreamKeyGenerator.platform.system", return_value="Windows"), \
                 patch("StreamLabsTikTokStreamKeyGenerator.os.path.expandvars",
                       return_value=os.path.join(directory, "*")):
                names = {os.path.basename(path) for path in local_token_files()}
        self.assertEqual(names, {"a.log", "b.ldb"})

    def test_unsupported_platform_returns_no_files(self):
        with patch("StreamLabsTikTokStreamKeyGenerator.platform.system", return_value="Linux"):
            self.assertEqual(local_token_files(), [])


if __name__ == "__main__":
    unittest.main()
