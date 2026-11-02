"""Tests for report rendering and export."""

from __future__ import annotations

import csv
import json
import unittest

from jar.journal import Journal
from jar.reports import export_report, report_text

from .helpers import SandboxTestCase


class ReportTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        journal = Journal(self.data_dir / "report.db")
        batch = journal.start_batch()
        journal.record(batch, "move", "/tmp/a.txt", "/tmp/Documents/a.txt", category="Documents", size=10)
        journal.record(batch, "move", "/tmp/b.jpg", "/tmp/Pictures/b.jpg", category="Images", size=20)
        journal.record(batch, "delete", "/tmp/c.bin", None, category="Executables", size=5)
        journal.finish_batch(batch, moved=2, failed=0, total=3)
        self.stats = journal.stats()
        journal.close()

    def test_text_report_contains_sections(self):
        text = report_text(self.stats)
        for section in ("JAR report", "By category", "Top extensions", "Last 7 days", "Actions"):
            self.assertIn(section, text)
        self.assertIn("Documents", text)

    def test_json_export(self):
        target = self.base / "report.json"
        path = export_report(self.stats, target)
        self.assertEqual(path, target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["moved"], 2)
        self.assertEqual(payload["bytes_moved"], 30)

    def test_markdown_export(self):
        target = self.base / "report.md"
        export_report(self.stats, target, "md")
        text = target.read_text(encoding="utf-8")
        self.assertIn("JAR report", text)
        self.assertIn("By category", text)

    def test_csv_and_tsv_export(self):
        for name, delimiter in (("report.csv", ","), ("report.tsv", "\t")):
            target = self.base / name
            export_report(self.stats, target)
            with target.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter=delimiter))
            self.assertTrue(rows)
            self.assertEqual(set(rows[0]), {"section", "name", "count", "bytes"})

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            export_report(self.stats, self.base / "report.xml", "xml")


if __name__ == "__main__":
    unittest.main()
