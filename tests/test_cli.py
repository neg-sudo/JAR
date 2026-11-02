"""CLI integration tests using the real argparse entry point."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from jar.cli import main

from .helpers import SandboxTestCase


def run(*argv: str):
    """Run the CLI, returning (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class BasicCommandTests(SandboxTestCase):
    def test_version(self):
        code, out, _err = run("version")
        self.assertEqual(code, 0)
        self.assertIn("JAR 2.0.0", out)
        self.assertIn("Just Automated Routing", out)

    def test_version_json(self):
        code, out, _err = run("--json", "version")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["name"], "JAR")
        self.assertEqual(payload["version"], "2.0.0")

    def test_help(self):
        with self.assertRaises(SystemExit) as raised:
            run("--help")
        self.assertEqual(raised.exception.code, 0)

    def test_completions(self):
        for shell in ("bash", "zsh", "fish"):
            code, out, _err = run("completions", shell)
            self.assertEqual(code, 0)
            self.assertIn("jar", out)

    def test_doctor(self):
        code, out, _err = run("doctor", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"])


class ConfigCommandTests(SandboxTestCase):
    def test_config_paths(self):
        code, out, _err = run("config", "path", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["config_file"], str(self.config.paths.config_file))

    def test_config_show_get_set_unset(self):
        code, out, _err = run("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["dest_root"], str(self.dest))

        code, out, _err = run("config", "get", "dest_root")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(self.dest))

        code, out, _err = run("config", "set", "conflict", "skip")
        self.assertEqual(code, 0)
        self.assertIn("conflict", out)
        self.assertEqual(self.reload().get("conflict"), "skip")

        code, _out, _err = run("config", "unset", "conflict")
        self.assertEqual(code, 0)
        self.assertEqual(self.reload().get("conflict"), "rename")

        code, _out, err = run("config", "unset", "conflict")
        self.assertEqual(code, 1)
        self.assertIn("not set", err)

    def test_config_validation_and_init(self):
        code, out, _err = run("config", "validate")
        self.assertEqual(code, 0, out)
        self.assertIn("valid", out.lower())

        code, out, _err = run("config", "init", "--force", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["created"])

    def test_profiles(self):
        code, _out, _err = run("config", "profiles", "--create", "media")
        self.assertEqual(code, 0)
        code, _out, _err = run("config", "profiles", "--use", "media")
        self.assertEqual(code, 0)
        code, out, _err = run("config", "profiles", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["active"], "media")
        self.assertIn("media", payload["profiles"])

        code, _out, _err = run("config", "profiles", "--delete", "media")
        self.assertEqual(code, 0)

    def test_migrate(self):
        legacy = self.base / "legacy.json"
        legacy.write_text(json.dumps({"watchDirs": [str(self.inbox)], "mode": "local"}), encoding="utf-8")
        code, out, _err = run("config", "migrate", "--from", str(legacy), "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["migrated"]["mode"], "local")


class ScanOrganizeTests(SandboxTestCase):
    def test_scan_json(self):
        self.write("a.txt", "a")
        self.write("b.jpg", "b")
        code, out, _err = run("scan", str(self.inbox), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["moves"], 2)

    def test_scan_stats(self):
        self.write("a.txt", "a")
        self.write("b.jpg", "b")
        code, out, _err = run("scan", str(self.inbox), "--stats")
        self.assertEqual(code, 0)
        self.assertIn("By category", out)
        self.assertIn("Documents", out)

    def test_organize_dry_run_json(self):
        source = self.write("a.txt", "a")
        code, out, _err = run("organize", str(self.inbox), "--dry-run", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(len(payload["plan"]["items"]), 1)
        self.assertTrue(source.exists())

    def test_organize_and_undo_json(self):
        source = self.write("a.txt", "a")
        code, out, _err = run("organize", str(self.inbox), "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["result"]["moved"], 1)
        self.assertFalse(source.exists())
        self.assertTrue((self.dest / "Documents" / "a.txt").exists())

        code, out, _err = run("history", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out))

        code, out, _err = run("undo", "--yes", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["restored"], 1)
        self.assertTrue(source.exists())

    def test_organize_nothing_to_do(self):
        code, out, _err = run("organize", str(self.inbox), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIsNone(payload["result"])

    def test_undo_nothing(self):
        code, out, _err = run("undo", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["restored"], 0)

    def test_watch_once(self):
        source = self.write("a.txt", "a")
        code, out, _err = run("watch", "--once", "--json")
        self.assertEqual(code, 0, out)
        self.assertFalse(source.exists())
        self.assertTrue((self.dest / "Documents" / "a.txt").exists())

    def test_conflict_and_filters(self):
        self.write("a.txt", "a")
        self.write("b.bin", "x" * 2048)
        code, out, _err = run(
            "organize", str(self.inbox), "--min-size", "1KB", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["plan"]["items"]), 1)
        self.assertEqual(payload["plan"]["items"][0]["category"], "Executables")

        code, out, _err = run(
            "organize", str(self.inbox), "--category", "Documents", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["plan"]["items"]), 1)
        self.assertEqual(payload["plan"]["items"][0]["category"], "Documents")

    def test_local_mode(self):
        source = self.write("pic.png", "img")
        code, _out, _err = run("organize", str(self.inbox), "--mode", "local")
        self.assertEqual(code, 0)
        self.assertFalse(source.exists())
        self.assertTrue((self.inbox / "Pictures" / "pic.png").exists())


class HistoryStatsTests(SandboxTestCase):
    def test_stats_export(self):
        self.write("a.txt", "a")
        run("organize", str(self.inbox), "--json")
        code, out, _err = run("stats", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["moved"], 1)

        report = self.base / "report.md"
        code, out, _err = run("stats", "--export", str(report), "--format", "md")
        self.assertEqual(code, 0)
        self.assertTrue(report.exists())
        self.assertIn("JAR report", report.read_text(encoding="utf-8"))

    def test_history_batches_and_search(self):
        self.write("a.txt", "a")
        run("organize", str(self.inbox), "--json")
        code, out, _err = run("history", "--batches", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 1)
        code, out, _err = run("history", "--search", "a.txt", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out))

    def test_history_clear(self):
        self.write("a.txt", "a")
        run("organize", str(self.inbox), "--json")
        code, out, _err = run("history", "--clear", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["cleared"])
        code, out, _err = run("history", "--json")
        self.assertEqual(json.loads(out), [])


class DuplicateCommandTests(SandboxTestCase):
    def test_duplicates_json(self):
        self.write("a.txt", "same")
        self.write("b.txt", "same")
        code, out, _err = run("duplicates", str(self.inbox), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["groups"]), 1)
        self.assertEqual(payload["files"], 2)

    def test_duplicates_remove_and_undo(self):
        self.write("a.txt", "same")
        self.write("b.txt", "same")
        code, out, _err = run(
            "duplicates", str(self.inbox), "--trash", "--keep", "first", "--yes", "--json"
        )
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(len(payload["removal"]["removed"]), 1)
        self.assertEqual(len(list(self.inbox.glob("*.txt"))), 1)

        code, out, _err = run("quarantine", "list", "--json")
        self.assertEqual(code, 0)
        items = json.loads(out)
        self.assertEqual(len(items), 1)

        code, out, _err = run("undo", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(list(self.inbox.glob("*.txt"))), 2)

    def test_duplicates_dry_run(self):
        self.write("a.txt", "same")
        self.write("b.txt", "same")
        code, out, _err = run(
            "duplicates", str(self.inbox), "--delete", "--yes", "--dry-run", "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["removal"]["removed"]), 1)
        self.assertEqual(len(list(self.inbox.glob("*.txt"))), 2)


class QuarantineCommandTests(SandboxTestCase):
    def test_restore_and_purge(self):
        from jar.trash import list_quarantine, quarantine_file

        source = self.write("report.txt", "content")
        quarantine_file(source, self.config.quarantine_dir)
        relative = list_quarantine(self.config.quarantine_dir)[0]["name"]

        restore_dir = self.base / "restored"
        code, out, _err = run(
            "quarantine", "restore", relative, "--to", str(restore_dir), "--json"
        )
        self.assertEqual(code, 0, out)
        self.assertTrue((restore_dir / "report.txt").exists())

        code, _out, _err = run("quarantine", "purge", "--older-than", "0s", "--yes", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(list_quarantine(self.config.quarantine_dir), [])

    def test_empty_list(self):
        code, out, _err = run("quarantine", "list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])


class RulesCommandTests(SandboxTestCase):
    def test_rules_lifecycle(self):
        code, out, _err = run("rules", "list", "--custom", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])

        code, _out, _err = run(
            "rules", "add", "--name", "zips", "--category", "Archives",
            "--ext", "zip,rar", "--dest", "Bundles", "--priority", "5",
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(self.reload().get("rules")), 1)

        code, out, _err = run("rules", "list", "--custom", "--json")
        payload = json.loads(out)
        self.assertEqual(payload[0]["name"], "zips")
        self.assertEqual(payload[0]["extensions"], [".zip", ".rar"])

        source = self.write("bundle.zip", "x")
        code, out, _err = run("rules", "test", str(source), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["category"], "Archives")
        self.assertIn("Bundles", payload["destination"])

        code, _out, _err = run("rules", "disable", "zips")
        self.assertEqual(code, 0)
        code, out, _err = run("rules", "list", "--custom", "--json")
        self.assertFalse(json.loads(out)[0]["enabled"])

        code, _out, _err = run("rules", "remove", "zips")
        self.assertEqual(code, 0)
        self.assertEqual(self.reload().get("rules"), [])

    def test_add_requires_matcher(self):
        code, _out, err = run("rules", "add", "--name", "nothing", "--category", "X")
        self.assertEqual(code, 1)
        self.assertIn("matcher", err)


if __name__ == "__main__":
    unittest.main()
