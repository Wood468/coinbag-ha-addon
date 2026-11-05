import os
import pathlib
import secrets
import tempfile
import unittest

from ingress import read_token


class TokenFileTests(unittest.TestCase):
    def test_private_token_and_unsafe_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'token'
            token = secrets.token_urlsafe(32)
            path.write_text(token)
            path.chmod(0o600)
            self.assertEqual(read_token(path), token)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                read_token(path)
            link = path.with_name('link')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                read_token(link)
            fifo = path.with_name('fifo')
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(ValueError):
                read_token(fifo)
