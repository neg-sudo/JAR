"""Shared test helpers for JAR's stdlib-only test suite."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jar.config import Config

ENV_KEYS = ("JAR_CONFIG_DIR", "JAR_DATA_DIR", "JAR_CONFIG_FILE", "NO_COLOR")


class SandboxTestCase(unittest.TestCase):
    """Create an isolated config/data/inbox sandbox for every test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="jar-tests-")
        self.base = Path(self._tmp.name)
        self.config_dir = self.base / "config"
        self.data_dir = self.base / "data"
        self.inbox = self.base / "inbox"
        self.dest = self.base / "sorted"
        for directory in (self.config_dir, self.data_dir, self.inbox, self.dest):
            directory.mkdir(parents=True, exist_ok=True)

        self._old_env = {key: os.environ.get(key) for key in ENV_KEYS}
        os.environ["JAR_CONFIG_DIR"] = str(self.config_dir)
        os.environ["JAR_DATA_DIR"] = str(self.data_dir)
        os.environ["NO_COLOR"] = "1"
        os.environ.pop("JAR_CONFIG_FILE", None)

        self.config = Config()
        self.config.create_default()
        self.config.set("watch_dirs", [str(self.inbox)])
        self.config.set("dest_root", str(self.dest))
        self.config.set("notifications", False)
        self.config.save()
        self.config = Config()

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    # ----------------------------------------------------------------- helpers
    def write(self, name: str, content: str = "x", folder: Path | None = None) -> Path:
        folder = folder or self.inbox
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(content, encoding="utf-8")
        return path

    def reload(self) -> Config:
        self.config = Config()
        return self.config

    def set(self, key: str, value) -> Config:
        self.config.set(key, value)
        self.config.save()
        return self.reload()
