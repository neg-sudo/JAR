"""Tests for path safety, filename hygiene and the lock file."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jar.errors import LockError, SafetyError
from jar.safety import (
    FileLock,
    apply_name_policy,
    ensure_safe_destination,
    is_hidden_path,
    is_protected_root,
    normalize_filename,
    sanitize_filename,
    unique_path,
)


class FilenameTests(unittest.TestCase):
    def test_sanitize_removes_forbidden_characters(self):
        self.assertEqual(sanitize_filename("a<b>c.txt"), "a_b_c.txt")
        self.assertEqual(sanitize_filename("what?.txt"), "what_.txt")
        self.assertEqual(sanitize_filename("  spaced  .txt"), "spaced.txt")
        self.assertEqual(sanitize_filename(""), "file")

    def test_sanitize_reserved_windows_names(self):
        self.assertEqual(sanitize_filename("CON.txt"), "_CON.txt")
        self.assertEqual(sanitize_filename("lpt9.log"), "_lpt9.log")

    def test_sanitize_length(self):
        result = sanitize_filename("a" * 400 + ".txt", max_length=50)
        self.assertLessEqual(len(result), 50)
        self.assertTrue(result.endswith(".txt"))

    def test_normalize_collapses_whitespace(self):
        self.assertEqual(normalize_filename("my   report  .pdf"), "my report.pdf")
        self.assertEqual(normalize_filename("My File.TXT", lowercase=True), "my file.TXT")

    def test_apply_name_policy_order(self):
        self.assertEqual(
            apply_name_policy("a  b?.txt", sanitize=True, normalize=True),
            "a b_.txt",
        )

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "file.txt").write_text("x", encoding="utf-8")
            (folder / "file (1).txt").write_text("x", encoding="utf-8")
            self.assertEqual(unique_path(folder, "file.txt").name, "file (2).txt")
            self.assertEqual(unique_path(folder, "other.txt").name, "other.txt")


class SafetyTests(unittest.TestCase):
    def test_protected_roots(self):
        self.assertTrue(is_protected_root(Path.home()))
        self.assertTrue(is_protected_root(Path("/") if os.name == "posix" else Path("C:\\")))
        self.assertFalse(is_protected_root(Path.home() / "Downloads"))

    def test_ensure_safe_destination(self):
        base = Path("/tmp/jar-safe")
        self.assertEqual(ensure_safe_destination(base / "a", base), base / "a")
        with self.assertRaises(SafetyError):
            ensure_safe_destination(Path("/tmp/elsewhere"), base)

    def test_hidden_path(self):
        self.assertTrue(is_hidden_path(Path("/home/user/.config/file")))
        self.assertFalse(is_hidden_path(Path("/home/user/file.txt")))


class LockTests(unittest.TestCase):
    def test_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jar.lock"
            first = FileLock(path)
            first.acquire()
            self.assertTrue(path.exists())
            with self.assertRaises(LockError):
                FileLock(path, timeout=0).acquire()
            first.release()
            self.assertFalse(path.exists())
            second = FileLock(path)
            with second:
                self.assertTrue(path.exists())

    def test_stale_lock_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jar.lock"
            path.write_text("999999 0\n", encoding="utf-8")
            lock = FileLock(path, timeout=0, stale_after=0)
            with lock:
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
