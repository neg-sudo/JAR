"""Tests for configuration loading, profiles, validation and migration."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jar.config import CONFIG_VERSION, Config, default_config, resolve_paths
from jar.errors import ConfigError

from .helpers import SandboxTestCase


class DefaultConfigTests(unittest.TestCase):
    def test_defaults_are_independent_copies(self):
        first = default_config()
        second = default_config()
        first["watch_dirs"].append("/tmp/x")
        first["categories"]["Images"].append(".fake")
        self.assertNotIn("/tmp/x", second["watch_dirs"])
        self.assertNotIn(".fake", second["categories"]["Images"])

    def test_default_contract(self):
        data = default_config()
        self.assertEqual(data["version"], CONFIG_VERSION)
        self.assertEqual(data["mode"], "global")
        self.assertIn("rename", data["conflict"])
        self.assertTrue(data["ignore_hidden"])
        self.assertIn("rules", data)


class ConfigFileTests(SandboxTestCase):
    def test_create_default_and_paths(self):
        self.assertTrue(self.config.paths.config_file.exists())
        payload = json.loads(self.config.paths.config_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], CONFIG_VERSION)
        self.assertTrue(self.config.exists)

    def test_create_default_refuses_overwrite(self):
        with self.assertRaises(ConfigError):
            self.config.create_default()
        self.config.create_default(force=True)

    def test_get_set_unset_persist(self):
        self.config.set("conflict", "skip")
        self.config.set("hooks.timeout", 25)
        self.config.save()
        reloaded = Config()
        self.assertEqual(reloaded.get("conflict"), "skip")
        self.assertEqual(reloaded.get("hooks.timeout"), 25)

        self.assertTrue(reloaded.unset("hooks.timeout"))
        reloaded.save()
        self.assertEqual(Config().get("hooks.timeout"), 10)

    def test_invalid_json_raises(self):
        self.config.paths.config_file.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            Config()

    def test_invalid_root_type_raises(self):
        self.config.paths.config_file.write_text("[]", encoding="utf-8")
        with self.assertRaises(ConfigError):
            Config()

    def test_with_overrides_does_not_mutate_source(self):
        clone = self.config.with_overrides({"conflict": "trash", "dest_root": "/tmp/other"})
        self.assertEqual(clone.get("conflict"), "trash")
        self.assertEqual(self.config.get("conflict"), "rename")

    def test_describe_contains_paths(self):
        described = self.config.describe()
        self.assertEqual(described["profile"], "default")
        self.assertIn("config_file", described)
        self.assertIn("data_dir", described)


class ProfileTests(SandboxTestCase):
    def test_profiles_merge_and_persist(self):
        self.config.create_profile("media", {"dest_root": "/tmp/media", "conflict": "skip"})
        self.config.save()
        profiles = Config(profile="media")
        self.assertEqual(profiles.profile, "media")
        self.assertEqual(profiles.get("conflict"), "skip")
        self.assertEqual(
            profiles.destination_root, Path("/tmp/media").resolve(strict=False)
        )
        self.assertIn("media", profiles.profile_names())

    def test_unknown_profile_raises(self):
        with self.assertRaises(ConfigError):
            Config(profile="missing")

    def test_use_and_delete_profile(self):
        self.config.create_profile("work")
        self.config.save()
        self.config.use_profile("work")
        self.config.save()
        self.assertEqual(Config().profile, "work")
        self.assertTrue(self.config.delete_profile("work"))
        self.config.save()
        self.assertEqual(Config().profile, "default")
        with self.assertRaises(ConfigError):
            self.config.delete_profile("default")

    def test_profile_set_writes_into_profile(self):
        self.config.create_profile("work")
        self.config.use_profile("work")
        self.config.set("conflict", "dedupe")
        self.config.save()
        self.assertEqual(Config(profile="work").get("conflict"), "dedupe")
        self.assertEqual(Config(profile="default").get("conflict"), "rename")


class ValidationTests(SandboxTestCase):
    def test_valid_configuration_has_no_errors(self):
        issues = self.config.validate()
        errors = [issue for issue in issues if issue[0] == "error"]
        self.assertEqual(errors, [])

    def test_detects_invalid_enum_values(self):
        self.config.set("mode", "sideways")
        self.config.set("conflict", "explode")
        errors = [message for level, message in self.config.validate() if level == "error"]
        self.assertTrue(any("mode" in message for message in errors))
        self.assertTrue(any("conflict" in message for message in errors))

    def test_detects_bad_rules_and_regex(self):
        self.config.set(
            "rules",
            [
                {"name": "broken", "category": "", "regex": "("},
                {"name": "no-matcher", "category": "Documents"},
            ],
        )
        messages = [message for _level, message in self.config.validate()]
        self.assertTrue(any("missing a category" in message for message in messages))
        self.assertTrue(any("invalid regex" in message for message in messages))
        self.assertTrue(any("never match" in message for message in messages))

    def test_detects_missing_watch_folder_as_warning(self):
        self.config.set("watch_dirs", [str(self.base / "does-not-exist")])
        warnings = [message for level, message in self.config.validate() if level == "warning"]
        self.assertTrue(any("does not exist" in message for message in warnings))


class MigrationTests(SandboxTestCase):
    def test_migrate_legacy_keys(self):
        legacy = self.base / "legacy.json"
        legacy.write_text(
            json.dumps(
                {
                    "watchDirs": ["/tmp/one", "/tmp/two"],
                    "mode": "Mode 2 - Local",
                    "destRoot": "/tmp/dest",
                }
            ),
            encoding="utf-8",
        )
        migrated = self.config.migrate_from(legacy)
        self.assertEqual(migrated["watch_dirs"], ["/tmp/one", "/tmp/two"])
        self.assertEqual(migrated["mode"], "local")
        self.assertEqual(migrated["dest_root"], "/tmp/dest")
        self.config.save()
        reloaded = Config()
        self.assertEqual(reloaded.get("mode"), "local")

    def test_migrate_rejects_non_object(self):
        legacy = self.base / "legacy.json"
        legacy.write_text("[]", encoding="utf-8")
        with self.assertRaises(ConfigError):
            self.config.migrate_from(legacy)


class PathResolutionTests(unittest.TestCase):
    def test_env_paths_are_honoured(self):
        paths = resolve_paths()
        self.assertEqual(paths.config_file.name, "config.json")
        self.assertEqual(paths.db_file.name, "jar.db")


if __name__ == "__main__":
    unittest.main()
