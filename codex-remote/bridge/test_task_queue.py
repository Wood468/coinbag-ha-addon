"""Tests for the isolated task queue; no Codex invocation or network needed."""
import pathlib
import tempfile
import unittest
from unittest import mock

from task_queue import TaskQueue, redact


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / "go-field-notes").mkdir()
        self.queue = TaskQueue(self.root)

    def test_unknown_project_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.submit("../../config", "check")

    def test_empty_prompt_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.submit("go-field-notes", "")

    def test_oversized_prompt_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.submit("go-field-notes", "x" * 4001)

    def test_missing_workspace_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.queue.submit("book-requests", "check")

    def test_symlink_workspace_escape_rejected(self):
        (self.root / "book-requests").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.queue.submit("book-requests", "check")

    def test_redaction(self):
        self.assertNotIn("github_pat_", redact("github_pat_" + "a" * 30))

    def test_invalid_task_id_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.get("../other")


if __name__ == "__main__":
    unittest.main()
