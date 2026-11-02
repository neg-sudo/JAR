"""Tests for the SQLite journal."""

from __future__ import annotations

import unittest

from jar.journal import Journal

from .helpers import SandboxTestCase


class JournalTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.data_dir / "journal.db")

    def tearDown(self):
        self.journal.close()
        super().tearDown()

    def test_batch_and_operation_lifecycle(self):
        batch = self.journal.start_batch(mode="organize", profile="default", total=2)
        first = self.journal.record(batch, "move", "/tmp/a.txt", "/tmp/Documents/a.txt", category="Documents", size=10)
        self.journal.record(batch, "move", "/tmp/b.txt", "/tmp/Documents/b.txt", category="Documents", size=20)
        self.journal.finish_batch(batch, moved=2, skipped=0, failed=0, total=2)

        stored = self.journal.batch(batch)
        self.assertEqual(stored["moved"], 2)
        self.assertIsNotNone(stored["finished"])
        self.assertEqual(len(self.journal.batches()), 1)
        operations = self.journal.operations()
        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[0]["action"], "move")

        self.journal.mark_undone(first)
        self.assertEqual(self.journal.operations(batch_id=batch)[-1]["undone"], 1)

    def test_operations_filters_and_search(self):
        batch = self.journal.start_batch()
        self.journal.record(batch, "move", "/tmp/report.pdf", "/tmp/Documents/report.pdf", category="Documents")
        self.journal.record(batch, "skip", "/tmp/other.txt", None, status="skipped", error="duplicate")
        self.journal.record(batch, "move", "/tmp/fail.txt", "/tmp/x/fail.txt", status="error", error="denied")

        self.assertEqual(len(self.journal.operations(status="skipped")), 1)
        self.assertEqual(len(self.journal.operations(action="move")), 2)
        self.assertEqual(len(self.journal.operations(search="duplicate")), 1)
        self.assertEqual(len(self.journal.search("report.pdf")), 1)
        self.assertEqual(len(self.journal.operations(batch_id=batch)), 3)

    def test_stats(self):
        batch = self.journal.start_batch()
        self.journal.record(batch, "move", "/tmp/a.txt", "/tmp/Documents/a.txt", category="Documents", size=100)
        self.journal.record(batch, "move", "/tmp/b.jpg", "/tmp/Pictures/b.jpg", category="Images", size=200)
        self.journal.record(batch, "delete", "/tmp/old.bin", None, category="Executables", size=50)
        self.journal.record(batch, "move", "/tmp/bad.txt", "/tmp/x/bad.txt", status="error", error="no")
        self.journal.finish_batch(batch, moved=2, skipped=0, failed=1, total=3)

        stats = self.journal.stats()
        self.assertEqual(stats["moved"], 2)
        self.assertEqual(stats["trashed"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["bytes_moved"], 300)
        self.assertEqual(stats["bytes_reclaimed"], 50)
        self.assertGreaterEqual(len(stats["by_category"]), 2)
        self.assertEqual(len(stats["last_7_days"]), 7)
        self.assertGreater(stats["db_bytes"], 0)

    def test_undo_candidates_ignore_undone_and_undo_batches(self):
        batch = self.journal.start_batch(mode="organize")
        operation = self.journal.record(batch, "move", "/tmp/a.txt", "/tmp/Documents/a.txt")
        self.journal.finish_batch(batch, moved=1)

        batches, operations = self.journal.undo_candidates()
        self.assertEqual([b["id"] for b in batches], [batch])
        self.assertEqual(len(operations), 1)

        self.journal.mark_undone(operation)
        self.assertEqual(self.journal.undo_candidates(), ([], []))

        second = self.journal.start_batch(mode="organize")
        self.journal.record(second, "move", "/tmp/b.txt", "/tmp/Documents/b.txt")
        self.journal.finish_batch(second, moved=1)
        undo_batch = self.journal.start_batch(mode="undo")
        self.journal.record(undo_batch, "restore", "/tmp/Documents/b.txt", "/tmp/b.txt")
        self.journal.finish_batch(undo_batch, moved=1)

        batches, operations = self.journal.undo_candidates()
        self.assertEqual([b["id"] for b in batches], [second])
        self.assertEqual(len(operations), 1)

    def test_clear_and_vacuum(self):
        batch = self.journal.start_batch()
        self.journal.record(batch, "move", "/tmp/a.txt", "/tmp/b.txt")
        self.journal.finish_batch(batch, moved=1)
        self.journal.clear()
        self.assertEqual(self.journal.batches(), [])
        self.assertEqual(self.journal.operations(), [])
        self.journal.vacuum()
        self.assertEqual(self.journal.stats()["operations"], 0)


if __name__ == "__main__":
    unittest.main()
