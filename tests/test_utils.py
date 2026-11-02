"""Tests for small utilities."""

from __future__ import annotations

import unittest
from pathlib import Path

from jar.utils import (
    deep_get,
    deep_merge,
    deep_set,
    deep_unset,
    expand_path,
    format_table,
    human_duration,
    human_size,
    parse_duration,
    parse_size,
    path_is_within,
    split_csv,
    truncate,
    truncate_middle,
)


class SizeAndDurationTests(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size("1k"), 1024)
        self.assertEqual(parse_size("1.5 KB"), 1536)
        self.assertEqual(parse_size("2mb"), 2 * 1024**2)
        self.assertEqual(parse_size("1GiB"), 1024**3)
        self.assertEqual(parse_size(None), 0)
        self.assertEqual(parse_size(42), 42)

    def test_parse_size_errors(self):
        with self.assertRaises(ValueError):
            parse_size("nope")
        with self.assertRaises(ValueError):
            parse_size("10 parsecs")

    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1024), "1 KB")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(None), "-")

    def test_parse_duration(self):
        self.assertEqual(parse_duration("90s"), 90)
        self.assertEqual(parse_duration("5m"), 300)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("1w"), 604800)
        self.assertEqual(parse_duration(None), 0)
        with self.assertRaises(ValueError):
            parse_duration("soon")

    def test_human_duration(self):
        self.assertEqual(human_duration(45), "45s")
        self.assertEqual(human_duration(3661), "1h 1m 1s")
        self.assertEqual(human_duration(None), "-")


class DictAndPathTests(unittest.TestCase):
    def test_deep_get_set_unset(self):
        data: dict = {}
        deep_set(data, "a.b.c", 3)
        self.assertEqual(data, {"a": {"b": {"c": 3}}})
        self.assertEqual(deep_get(data, "a.b.c"), 3)
        self.assertEqual(deep_get(data, "a.b.missing", "fallback"), "fallback")
        self.assertTrue(deep_unset(data, "a.b.c"))
        self.assertFalse(deep_unset(data, "a.b.c"))

    def test_deep_merge_is_a_copy(self):
        base = {"a": {"x": 1, "y": 2}}
        merged = deep_merge(base, {"a": {"y": 20}, "b": 3})
        self.assertEqual(merged, {"a": {"x": 1, "y": 20}, "b": 3})
        self.assertEqual(base, {"a": {"x": 1, "y": 2}})

    def test_path_is_within(self):
        base = Path("/tmp/example")
        self.assertTrue(path_is_within(base / "child", base))
        self.assertTrue(path_is_within(base, base))
        self.assertFalse(path_is_within(Path("/tmp/example-other"), base))

    def test_expand_path(self):
        self.assertIsNone(expand_path(""))
        self.assertEqual(expand_path("child", Path("/tmp/base")), Path("/tmp/base/child"))
        self.assertTrue(expand_path("~/thing").is_absolute())

    def test_split_csv(self):
        self.assertEqual(split_csv("a, b ,,c"), ["a", "b", "c"])
        self.assertEqual(split_csv(None), [])


class FormattingTests(unittest.TestCase):
    def test_truncate(self):
        self.assertEqual(truncate("hello", 10), "hello")
        self.assertEqual(truncate("hello world", 8), "hello...")
        self.assertEqual(truncate("hello", 0), "")

    def test_truncate_middle(self):
        text = "/very/long/path/to/some/file.txt"
        result = truncate_middle(text, 20)
        self.assertLessEqual(len(result), 20)
        self.assertIn("...", result)
        self.assertTrue(result.startswith("/very"))

    def test_format_table(self):
        table = format_table(["Name", "Size"], [["a.txt", "1 B"]])
        lines = table.splitlines()
        self.assertIn("Name", lines[0])
        self.assertTrue(set(lines[1].replace(" ", "")) == {"-"})
        self.assertIn("a.txt", lines[2])


if __name__ == "__main__":
    unittest.main()
