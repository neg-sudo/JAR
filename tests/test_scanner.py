"""Tests for file discovery and filtering."""

from __future__ import annotations

import unittest

from jar.scanner import iter_files, scan_candidates

from .helpers import SandboxTestCase


class ScannerTests(SandboxTestCase):
    def test_non_recursive_scan(self):
        self.write("a.txt", "a")
        self.write("b.jpg", "b")
        self.write("c.pdf", "c", self.inbox / "nested")
        names = {candidate.path.name for candidate in scan_candidates([self.inbox], self.config)}
        self.assertEqual(names, {"a.txt", "b.jpg"})

    def test_recursive_scan(self):
        self.write("a.txt", "a")
        self.write("c.pdf", "c", self.inbox / "nested")
        names = {
            candidate.path.name
            for candidate in scan_candidates([self.inbox], self.config, recursive=True)
        }
        self.assertEqual(names, {"a.txt", "c.pdf"})

    def test_candidates_are_sorted_and_have_matches(self):
        self.write("z.txt", "z")
        self.write("a.jpg", "a")
        candidates = scan_candidates([self.inbox], self.config)
        self.assertEqual([c.path.name for c in candidates], ["a.jpg", "z.txt"])
        self.assertEqual(candidates[0].match.category, "Images")
        self.assertEqual(candidates[1].match.category, "Documents")
        self.assertGreaterEqual(candidates[0].size, 1)

    def test_hidden_and_temporary_files_are_skipped(self):
        self.write(".hidden.txt")
        self.write("download.crdownload")
        self.write("visible.txt")
        names = {candidate.path.name for candidate in scan_candidates([self.inbox], self.config)}
        self.assertEqual(names, {"visible.txt"})

    def test_jarignore_is_honoured(self):
        self.write(".jarignore", "*.log\nprivate/\n")
        self.write("debug.log")
        self.write("keep.txt")
        self.write("secret.txt", folder=self.inbox / "private")
        names = {
            candidate.path.name
            for candidate in scan_candidates([self.inbox], self.config, recursive=True)
        }
        self.assertEqual(names, {"keep.txt"})

    def test_jarignore_directory_pattern_only_matches_relative_paths(self):
        # A parent folder called "private" must not make every file ignored;
        # this is a regression test for macOS, where /var resolves to
        # /private/var and the ignore pattern used to match the absolute path.
        nested_inbox = self.base / "private" / "inbox"
        self.write(".jarignore", "private/\n", nested_inbox)
        self.write("keep.txt", folder=nested_inbox)
        self.write("secret.txt", folder=nested_inbox / "private")
        names = {
            candidate.path.name
            for candidate in scan_candidates([nested_inbox], self.config, recursive=True)
        }
        self.assertEqual(names, {"keep.txt"})

    def test_category_filter(self):
        self.write("a.txt")
        self.write("b.jpg")
        only_images = scan_candidates([self.inbox], self.config, categories=["Images"])
        self.assertEqual([c.path.name for c in only_images], ["b.jpg"])

        self.set("exclude_categories", ["Documents"])
        names = {candidate.path.name for candidate in scan_candidates([self.inbox], self.config)}
        self.assertEqual(names, {"b.jpg"})

    def test_size_filters(self):
        self.write("small.txt", "a")
        self.write("large.txt", "x" * 2048)
        collected = scan_candidates([self.inbox], self.config)
        self.assertEqual(len(collected), 2)
        self.set("min_size", 1024)
        names = {candidate.path.name for candidate in scan_candidates([self.inbox], self.config)}
        self.assertEqual(names, {"large.txt"})
        self.set("min_size", 0)
        self.set("max_size", 10)
        names = {candidate.path.name for candidate in scan_candidates([self.inbox], self.config)}
        self.assertEqual(names, {"small.txt"})

    def test_files_already_in_destination_are_skipped(self):
        target = self.dest / "Documents" / "already.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        names = {candidate.path.name for candidate in scan_candidates([self.dest], self.config)}
        self.assertEqual(names, set())

    def test_direct_file_input(self):
        path = self.write("one.txt")
        candidates = scan_candidates([path], self.config)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].path, path)

    def test_iter_files_reports_errors_gracefully(self):
        errors = []
        files = list(
            iter_files(
                [self.base / "missing"],
                on_error=lambda path, exc: errors.append((path, exc)),
            )
        )
        self.assertEqual(files, [])
        self.assertEqual(errors, [])

    def test_protected_root_is_rejected(self):
        import os
        from pathlib import Path

        protected = Path.home()
        if os.name == "nt":
            protected = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        with self.assertRaises(ValueError):
            scan_candidates([protected], self.config)


if __name__ == "__main__":
    unittest.main()
