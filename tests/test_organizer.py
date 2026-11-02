"""End-to-end tests for planning, moving, conflicts, undo and dedupe."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from jar.errors import JarError, SafetyError
from jar.organizer import Organizer

from .helpers import SandboxTestCase


class OrganizerTestCase(SandboxTestCase):
    def organizer(self) -> Organizer:
        return Organizer(self.config)

    def test_plan_assigns_categories_and_destinations(self):
        self.write("a.txt", "alpha")
        self.write("b.jpg", "beta")
        self.write("c.unknownext", "gamma")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
        finally:
            organizer.close()
        destinations = {item.src.name: item.dst for item in plan.items}
        self.assertEqual(destinations["a.txt"], self.dest / "Documents" / "a.txt")
        self.assertEqual(destinations["b.jpg"], self.dest / "Pictures" / "b.jpg")
        self.assertEqual(destinations["c.unknownext"], self.dest / "Misc" / "c.unknownext")
        self.assertEqual(len(plan.moves), 3)
        self.assertEqual(plan.total_size, len("alpha") + len("beta") + len("gamma"))

    def test_dry_run_does_not_touch_files(self):
        source = self.write("a.txt", "alpha")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            result = organizer.execute(plan, dry_run=True)
        finally:
            organizer.close()
        self.assertTrue(source.exists())
        self.assertEqual(len(result.moved), 1)
        self.assertTrue(result.dry_run)

    def test_execute_moves_and_records_history(self):
        source = self.write("a.txt", "alpha")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            result = organizer.execute(plan, dry_run=False)
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.batch_id)
            self.assertEqual(len(result.moved), 1)
            self.assertEqual(result.bytes_moved, len("alpha"))
            self.assertFalse(source.exists())
            moved = self.dest / "Documents" / "a.txt"
            self.assertEqual(moved.read_text(encoding="utf-8"), "alpha")
            operations = organizer.journal.operations(batch_id=result.batch_id)
            self.assertEqual(operations[0]["action"], "move")
            self.assertEqual(operations[0]["status"], "ok")
        finally:
            organizer.close()

    def test_undo_restores_last_batch(self):
        source = self.write("a.txt", "alpha")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            result = organizer.execute(plan, dry_run=False)
            undo = organizer.undo(count=1)
            self.assertEqual(len(undo.restored), 1)
            self.assertTrue(source.exists())
            self.assertFalse((self.dest / "Documents" / "a.txt").exists())
            self.assertEqual(undo.batches, [result.batch_id])
            self.assertEqual(organizer.undo(count=1).restored, [])
        finally:
            organizer.close()

    def test_undo_dry_run(self):
        source = self.write("a.txt", "alpha")
        organizer = self.organizer()
        try:
            organizer.execute(organizer.plan([self.inbox]), dry_run=False)
            result = organizer.undo(count=1, dry_run=True)
            self.assertEqual(len(result.restored), 1)
            self.assertFalse(source.exists())
        finally:
            organizer.close()

    def test_undo_specific_batch(self):
        first = self.write("a.txt")
        second = self.write("b.txt")
        organizer = self.organizer()
        try:
            first_result = organizer.execute(organizer.plan([first]), dry_run=False)
            organizer.execute(organizer.plan([second]), dry_run=False)
            undo = organizer.undo(batch_id=first_result.batch_id)
            self.assertTrue(first.exists())
            self.assertFalse(second.exists())
        finally:
            organizer.close()

    def test_recursive_and_cleanup_empty_dirs(self):
        nested = self.inbox / "nested"
        self.write("deep.pdf", "pdf", nested)
        self.set("recursive", True)
        self.set("cleanup_empty_dirs", True)
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            result = organizer.execute(plan, dry_run=False)
        finally:
            organizer.close()
        self.assertEqual(len(result.moved), 1)
        self.assertFalse(nested.exists())
        self.assertTrue((self.dest / "Documents" / "deep.pdf").exists())

    def test_name_policy_is_applied(self):
        self.write("my   report.txt", "x")
        self.set("normalize_names", True)
        organizer = self.organizer()
        try:
            organizer.execute(organizer.plan([self.inbox]), dry_run=False)
        finally:
            organizer.close()
        self.assertTrue((self.dest / "Documents" / "my report.txt").exists())

    def test_invalid_destination_template_is_skipped(self):
        self.write("a.txt")
        self.set("destination_template", "../escape")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
        finally:
            organizer.close()
        self.assertEqual(len(plan.moves), 0)
        self.assertIn("invalid destination", plan.items[0].reason)

    def test_missing_source_between_plan_and_execute(self):
        source = self.write("a.txt")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            source.unlink()
            result = organizer.execute(plan, dry_run=False)
            self.assertEqual(len(result.skipped), 1)
            self.assertEqual(result.skipped[0]["reason"], "source disappeared")
        finally:
            organizer.close()

    def test_progress_callback(self):
        for index in range(3):
            self.write(f"file{index}.txt", str(index))
        events = []
        organizer = self.organizer()
        try:
            organizer.execute(
                organizer.plan([self.inbox]),
                dry_run=False,
                progress=lambda done, total, message: events.append((done, total)),
            )
        finally:
            organizer.close()
        self.assertEqual(events, [(1, 3), (2, 3), (3, 3)])

    def test_plan_errors(self):
        organizer = self.organizer()
        try:
            with self.assertRaises(JarError):
                organizer.plan([self.base / "missing"])
            with self.assertRaises(SafetyError):
                organizer.plan([Path.home()])
        finally:
            organizer.close()

    def test_no_folders_configured(self):
        self.set("watch_dirs", [])
        organizer = self.organizer()
        try:
            with self.assertRaises(JarError):
                organizer.plan([])
        finally:
            organizer.close()


class ConflictTests(OrganizerTestCase):
    def _prepare(self, existing_content: str, source_content: str) -> tuple[Path, Path]:
        source = self.write("report.txt", source_content)
        existing = self.dest / "Documents" / "report.txt"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text(existing_content, encoding="utf-8")
        return source, existing

    def _run(self) -> tuple[object, Organizer]:
        organizer = self.organizer()
        plan = organizer.plan([self.inbox])
        result = organizer.execute(plan, dry_run=False)
        return result, organizer

    def test_rename_strategy(self):
        self.set("conflict", "rename")
        self._prepare("old", "new")
        result, organizer = self._run()
        try:
            self.assertEqual(len(result.moved), 1)
            self.assertEqual(
                (self.dest / "Documents" / "report (1).txt").read_text(encoding="utf-8"),
                "new",
            )
            self.assertEqual(
                (self.dest / "Documents" / "report.txt").read_text(encoding="utf-8"),
                "old",
            )
        finally:
            organizer.close()

    def test_skip_strategy(self):
        self.set("conflict", "skip")
        self._prepare("old", "new")
        result, organizer = self._run()
        try:
            self.assertEqual(len(result.moved), 0)
            self.assertEqual(
                (self.dest / "Documents" / "report.txt").read_text(encoding="utf-8"),
                "old",
            )
        finally:
            organizer.close()

    def test_overwrite_strategy(self):
        self.set("conflict", "overwrite")
        self._prepare("old", "new")
        result, organizer = self._run()
        try:
            self.assertEqual(len(result.moved), 1)
            self.assertEqual(
                (self.dest / "Documents" / "report.txt").read_text(encoding="utf-8"),
                "new",
            )
            actions = [row["action"] for row in organizer.journal.operations()]
            self.assertIn("delete", actions)
        finally:
            organizer.close()

    def test_trash_strategy_quarantines_existing_file(self):
        self.set("conflict", "trash")
        self.set("use_trash", True)
        self._prepare("old", "new")
        result, organizer = self._run()
        try:
            self.assertEqual(len(result.moved), 1)
            self.assertEqual(
                (self.dest / "Documents" / "report.txt").read_text(encoding="utf-8"),
                "new",
            )
            quarantined = list((self.data_dir / "quarantine").rglob("*report.txt"))
            self.assertEqual(len(quarantined), 1)
        finally:
            organizer.close()

    def test_dedupe_strategy_skips_identical_file(self):
        self.set("conflict", "dedupe")
        self._prepare("same", "same")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            self.assertEqual(len(plan.moves), 0)
            self.assertIn("duplicate", plan.items[0].reason)
        finally:
            organizer.close()

    def test_dedupe_strategy_renames_different_file(self):
        self.set("conflict", "dedupe")
        self._prepare("old", "new")
        result, organizer = self._run()
        try:
            self.assertEqual(len(result.moved), 1)
            self.assertTrue((self.dest / "Documents" / "report (1).txt").exists())
        finally:
            organizer.close()

    def test_keep_newest_strategy(self):
        self.set("conflict", "keep_newest")
        source, existing = self._prepare("old", "new")
        os.utime(existing, (source.stat().st_mtime + 100, source.stat().st_mtime + 100))
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            self.assertEqual(len(plan.moves), 0)
        finally:
            organizer.close()

    def test_keep_oldest_strategy(self):
        self.set("conflict", "keep_oldest")
        source, existing = self._prepare("old", "new")
        os.utime(existing, (source.stat().st_mtime - 100, source.stat().st_mtime - 100))
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            self.assertEqual(len(plan.moves), 0)
        finally:
            organizer.close()

    def test_planned_conflicts_within_one_batch_are_renamed(self):
        self.write("a.txt", "one", self.inbox / "one")
        self.write("a.txt", "two", self.inbox / "two")
        self.set("destination_template", "Everything")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox], recursive=True)
            self.assertEqual(len(plan.moves), 2)
            names = sorted(item.dst.name for item in plan.moves)
            self.assertEqual(names, ["a (1).txt", "a.txt"])
            organizer.execute(plan, dry_run=False)
            self.assertTrue((self.dest / "Everything" / "a.txt").exists())
            self.assertTrue((self.dest / "Everything" / "a (1).txt").exists())
        finally:
            organizer.close()


class LocalModeTests(OrganizerTestCase):
    def test_local_mode_moves_into_file_parent(self):
        self.set("mode", "local")
        source = self.write("pic.png", "image")
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox])
            self.assertEqual(len(plan.moves), 1)
            result = organizer.execute(plan, dry_run=False)
        finally:
            organizer.close()
        self.assertFalse(source.exists())
        self.assertTrue((self.inbox / "Pictures" / "pic.png").exists())

    def test_local_mode_skips_already_sorted_files(self):
        self.set("mode", "local")
        nested = self.inbox / "Pictures"
        self.write("already.png", "x", nested)
        organizer = self.organizer()
        try:
            plan = organizer.plan([self.inbox], recursive=True)
        finally:
            organizer.close()
        self.assertEqual(len(plan.items), 0)


class DedupeTests(OrganizerTestCase):
    def test_scan_and_remove_duplicates_with_undo(self):
        self.write("a.txt", "same")
        self.write("b.txt", "same")
        self.write("c.txt", "different")
        organizer = self.organizer()
        try:
            groups = organizer.scan_duplicates([self.inbox])
            self.assertEqual(len(groups), 1)
            result = organizer.dedupe(groups, keep="first", dry_run=False)
            self.assertEqual(len(result.removed), 1)
            self.assertEqual(result.bytes_reclaimed, len("same"))
            self.assertEqual(len(list(self.inbox.glob("*.txt"))), 2)
            undo = organizer.undo(count=1)
            self.assertEqual(len(undo.restored), 1)
            self.assertEqual(len(list(self.inbox.glob("*.txt"))), 3)
        finally:
            organizer.close()

    def test_dedupe_dry_run(self):
        self.write("a.txt", "same")
        self.write("b.txt", "same")
        organizer = self.organizer()
        try:
            groups = organizer.scan_duplicates([self.inbox])
            result = organizer.dedupe(groups, dry_run=True)
            self.assertEqual(len(result.removed), 1)
            self.assertEqual(len(list(self.inbox.glob("*.txt"))), 2)
        finally:
            organizer.close()

    def test_scan_duplicates_requires_folders(self):
        organizer = self.organizer()
        try:
            with self.assertRaises(JarError):
                organizer.scan_duplicates([self.base / "missing"])
        finally:
            organizer.close()


if __name__ == "__main__":
    unittest.main()
