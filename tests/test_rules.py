"""Tests for classification, ignore handling and destination rendering."""

from __future__ import annotations

import unittest

from jar.categories import default_destination
from jar.errors import RuleError
from jar.rules import RuleEngine, build_rules, normalize_extension
from jar.utils import path_is_within

from .helpers import SandboxTestCase


class ExtensionTests(unittest.TestCase):
    def test_normalize_extension(self):
        self.assertEqual(normalize_extension("PDF"), ".pdf")
        self.assertEqual(normalize_extension(".JPG"), ".jpg")
        self.assertEqual(normalize_extension("  "), "")
        self.assertEqual(default_destination("Images"), "Pictures")
        self.assertEqual(default_destination("Code"), "Code")


class RuleEngineTests(SandboxTestCase):
    def test_builtin_classification(self):
        engine = RuleEngine(self.config)
        expected = {
            "photo.jpg": "Images",
            "movie.mp4": "Videos",
            "song.flac": "Audio",
            "book.epub": "Ebooks",
            "notes.md": "Documents",
            "data.json": "Data",
            "script.py": "Code",
            "archive.zip": "Archives",
            "installer.exe": "Installers",
            "unknown.xyz123": "Others",
        }
        for name, category in expected.items():
            path = self.write(name)
            self.assertEqual(engine.classify(path).category, category, name)

    def test_category_order_wins_for_shared_extensions(self):
        engine = RuleEngine(self.config)
        self.assertEqual(engine.classify(self.write("setup.exe")).category, "Installers")
        self.assertEqual(engine.classify(self.write("disk.iso")).category, "DiskImages")

    def test_destination_rendering(self):
        engine = RuleEngine(self.config)
        match = engine.classify(self.write("photo.jpg"))
        destination = engine.render_destination(self.inbox / "photo.jpg", match)
        self.assertEqual(destination, self.dest / "Pictures" / "photo.jpg")
        self.assertTrue(path_is_within(destination, self.dest))

    def test_custom_destination_template(self):
        self.set("destination_template", "{category}/{year}/{month}")
        engine = RuleEngine(self.config)
        path = self.write("report.pdf")
        match = engine.classify(path)
        destination = engine.render_destination(path, match)
        self.assertEqual(destination.parent.parent.parent, self.dest / "Documents")
        self.assertEqual(destination.name, "report.pdf")

    def test_date_subfolders(self):
        self.set("date_subfolders", True)
        engine = RuleEngine(self.config)
        path = self.write("report.pdf")
        destination = engine.render_destination(path, engine.classify(path))
        self.assertEqual(len(destination.relative_to(self.dest).parts), 4)

    def test_template_escape_is_rejected(self):
        self.set("destination_template", "../outside")
        engine = RuleEngine(self.config)
        path = self.write("report.pdf")
        with self.assertRaises(RuleError):
            engine.render_destination(path, engine.classify(path))

    def test_custom_rule_priority_and_regex(self):
        self.set(
            "rules",
            [
                {
                    "name": "screenshots",
                    "category": "Screenshots",
                    "priority": 1,
                    "regex": r"^shot[-_].*\.png$",
                    "destination": "Shots",
                },
                {
                    "name": "raw-photos",
                    "category": "RAW",
                    "priority": 2,
                    "extensions": ["png"],
                },
            ],
        )
        engine = RuleEngine(self.config)
        shot = engine.classify(self.write("shot-2026.png"))
        self.assertEqual(shot.category, "Screenshots")
        other = engine.classify(self.write("photo.png"))
        self.assertEqual(other.category, "RAW")

    def test_disabled_custom_rule_is_ignored(self):
        self.set(
            "rules",
            [
                {
                    "name": "off",
                    "category": "Special",
                    "extensions": ["txt"],
                    "enabled": False,
                }
            ],
        )
        engine = RuleEngine(self.config)
        self.assertEqual(engine.classify(self.write("a.txt")).category, "Documents")

    def test_invalid_regex_rule_is_skipped(self):
        self.set(
            "rules",
            [{"name": "bad", "category": "Special", "regex": "("}],
        )
        engine = RuleEngine(self.config)
        self.assertEqual(engine.classify(self.write("a.txt")).category, "Documents")

    def test_rule_matching_helpers(self):
        self.set(
            "rules",
            [
                {
                    "name": "large",
                    "category": "Large",
                    "extensions": ["bin"],
                    "min_size": 1024,
                }
            ],
        )
        engine = RuleEngine(self.config)
        self.assertEqual(engine.classify(self.write("small.bin", "x")).category, "Executables")
        self.assertEqual(engine.classify(self.write("big.bin", "x" * 2048)).category, "Large")

    def test_ignore_rules(self):
        engine = RuleEngine(self.config)
        self.assertTrue(engine.is_ignored(self.write(".hidden.txt")))
        self.assertTrue(engine.is_ignored(self.write("partial.crdownload")))
        self.assertTrue(engine.is_ignored(self.write("~$lock.docx")))
        self.assertFalse(engine.is_ignored(self.write("normal.txt")))

        self.write(".jarignore", "*.skip\n!keep.skip\nsecret/\n")
        self.assertTrue(engine.is_ignored(self.inbox / "file.skip", [self.inbox]))
        self.assertFalse(engine.is_ignored(self.inbox / "keep.skip", [self.inbox]))
        self.assertTrue(engine.is_ignored(self.inbox / "secret" / "thing.txt", [self.inbox]))
        self.assertTrue(engine.is_ignored_dir(self.inbox / "secret", [self.inbox]))

    def test_in_destination_global_and_local(self):
        self.set("mode", "global")
        engine = RuleEngine(self.config)
        self.assertTrue(engine.in_destination(self.dest / "Documents" / "a.txt"))
        self.assertFalse(engine.in_destination(self.inbox / "a.txt"))

        self.set("mode", "local")
        engine = RuleEngine(self.config)
        self.assertTrue(engine.in_destination(self.inbox / "Documents" / "a.txt"))
        self.assertFalse(engine.in_destination(self.inbox / "elsewhere" / "a.txt"))

    def test_build_rules_has_fallback(self):
        rules = build_rules(self.config.data)
        self.assertEqual(rules[-1].name, "fallback:Others")
        self.assertEqual(rules[-1].category, "Others")
        self.assertGreater(len(rules), 10)


if __name__ == "__main__":
    unittest.main()
