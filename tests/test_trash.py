"""Tests for quarantine and safe deletion helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from jar.trash import (
    delete_path,
    list_quarantine,
    purge_quarantine,
    quarantine_file,
    resolve_quarantine_item,
    restore_quarantine_item,
)

from .helpers import SandboxTestCase


class QuarantineTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.quarantine = self.data_dir / "quarantine"

    def test_quarantine_file_moves_and_lists(self):
        source = self.write("report.txt", "content")
        target = quarantine_file(source, self.quarantine)
        self.assertFalse(source.exists())
        self.assertTrue(target.exists())
        self.assertIn("__report.txt", target.name)

        items = list_quarantine(self.quarantine)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["size"], len("content"))
        self.assertIn("report.txt", items[0]["name"])

    def test_quarantine_name_collision(self):
        first = self.write("a.txt", "one", self.inbox / "one")
        second = self.write("a.txt", "two", self.inbox / "two")
        target_one = quarantine_file(first, self.quarantine)
        target_two = quarantine_file(second, self.quarantine)
        self.assertNotEqual(target_one, target_two)
        self.assertEqual(len(list_quarantine(self.quarantine)), 2)

    def test_restore_strips_timestamp_prefix(self):
        source = self.write("report.txt", "content")
        quarantine_file(source, self.quarantine)
        relative = list_quarantine(self.quarantine)[0]["name"]
        restored = restore_quarantine_item(self.quarantine, relative, self.base / "restored")
        self.assertEqual(restored.name, "report.txt")
        self.assertEqual(restored.read_text(encoding="utf-8"), "content")

    def test_restore_avoids_overwrite(self):
        source = self.write("report.txt", "content")
        quarantine_file(source, self.quarantine)
        relative = list_quarantine(self.quarantine)[0]["name"]
        target_dir = self.base / "restored"
        target_dir.mkdir()
        (target_dir / "report.txt").write_text("existing", encoding="utf-8")
        restored = restore_quarantine_item(self.quarantine, relative, target_dir)
        self.assertEqual(restored.name, "report (1).txt")

    def test_restore_rejects_escape(self):
        with self.assertRaises(ValueError):
            resolve_quarantine_item(self.quarantine, "../outside.txt")

    def test_restore_missing_item(self):
        with self.assertRaises(FileNotFoundError):
            restore_quarantine_item(self.quarantine, "nope.txt", self.base)

    def test_purge(self):
        first = self.write("old.txt", "old")
        second = self.write("new.txt", "new")
        quarantine_file(first, self.quarantine)
        quarantine_file(second, self.quarantine)
        removed = purge_quarantine(self.quarantine, older_than_seconds=0, dry_run=True)
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(list_quarantine(self.quarantine)), 2)
        removed = purge_quarantine(self.quarantine, older_than_seconds=0)
        self.assertEqual(len(removed), 2)
        self.assertEqual(list_quarantine(self.quarantine), [])

    def test_delete_path_to_quarantine(self):
        source = self.write("delete-me.txt", "x")
        target = delete_path(source, use_trash=True, quarantine_dir=self.quarantine)
        self.assertIsNotNone(target)
        self.assertTrue(target.exists())

    def test_delete_path_permanent(self):
        source = self.write("delete-me.txt", "x")
        target = delete_path(source, use_trash=False)
        self.assertIsNone(target)
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
