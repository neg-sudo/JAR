"""Tests for duplicate detection and keeper selection."""

from __future__ import annotations

import os
import unittest

from jar.duplicates import choose_keeper, file_digest, find_duplicates, remove_duplicates

from .helpers import SandboxTestCase


class DuplicateTests(SandboxTestCase):
    def test_digest_is_stable(self):
        first = self.write("a.bin", "same")
        second = self.write("b.bin", "same")
        self.assertEqual(file_digest(first), file_digest(second))
        self.assertNotEqual(file_digest(first), file_digest(self.write("c.bin", "other")))

    def test_find_duplicates_groups_identical_files(self):
        self.write("a.txt", "same-content")
        self.write("b.txt", "same-content")
        self.write("c.txt", "other-content")
        groups = find_duplicates(list(self.inbox.iterdir()))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].files), 2)
        self.assertEqual(groups[0].wasted_bytes, len("same-content"))

    def test_empty_files_optional(self):
        self.write("empty1.txt", "")
        self.write("empty2.txt", "")
        self.assertEqual(find_duplicates(list(self.inbox.iterdir())), [])
        groups = find_duplicates(list(self.inbox.iterdir()), include_empty=True)
        self.assertEqual(len(groups), 1)

    def test_different_sizes_are_not_hashed_together(self):
        self.write("a.txt", "short")
        self.write("b.txt", "much longer content")
        self.assertEqual(find_duplicates(list(self.inbox.iterdir())), [])

    def test_choose_keeper_strategies(self):
        first = self.write("first.txt", "same")
        second = self.write("second.txt", "same")
        os.utime(first, (1000, 1000))
        os.utime(second, (2000, 2000))
        groups = find_duplicates(list(self.inbox.iterdir()))
        group = groups[0]
        self.assertEqual(choose_keeper(group, "first"), sorted(group.files, key=str)[0])
        self.assertEqual(choose_keeper(group, "oldest"), first)
        self.assertEqual(choose_keeper(group, "newest"), second)
        shortest = choose_keeper(group, "shortest")
        self.assertEqual(shortest.name, min(("first.txt", "second.txt"), key=len))

    def test_remove_duplicates_dry_run(self):
        first = self.write("a.txt", "same")
        second = self.write("b.txt", "same")
        groups = find_duplicates([first, second])
        result = remove_duplicates(groups, dry_run=True)
        self.assertEqual(result.removed_count, 1)
        self.assertTrue(first.exists() and second.exists())

    def test_remove_duplicates_permanent(self):
        first = self.write("a.txt", "same")
        second = self.write("b.txt", "same")
        groups = find_duplicates([first, second])
        result = remove_duplicates(groups, dry_run=False, use_trash=False)
        self.assertEqual(result.removed_count, 1)
        self.assertEqual(len(list(self.inbox.iterdir())), 1)

    def test_remove_duplicates_to_quarantine(self):
        first = self.write("a.txt", "same")
        second = self.write("b.txt", "same")
        groups = find_duplicates([first, second])
        result = remove_duplicates(
            groups,
            dry_run=False,
            use_trash=True,
            quarantine_dir=self.data_dir / "quarantine",
        )
        self.assertEqual(result.removed_count, 1)
        self.assertTrue(any(target and target.exists() for _src, target in result.removed))


if __name__ == "__main__":
    unittest.main()
