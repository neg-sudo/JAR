"""Tests for the polling watcher."""

from __future__ import annotations

import threading
import time
import unittest

from jar.errors import JarError
from jar.watcher import WatchService

from .helpers import SandboxTestCase


class WatcherTests(SandboxTestCase):
    def test_requires_existing_folders(self):
        with self.assertRaises(JarError):
            WatchService(self.config, [self.base / "missing"], lambda path: None)
        self.set("watch_dirs", [])
        with self.assertRaises(JarError):
            WatchService(self.config, [], lambda path: None)
        service = WatchService(self.config, [self.inbox], lambda path: None)
        self.assertTrue(service.paths)

    def test_snapshot_and_eligibility(self):
        self.write("a.txt", "a")
        self.write(".hidden.txt", "hidden")
        service = WatchService(self.config, [self.inbox], lambda path: None)
        snapshot = service._snapshot()
        self.assertEqual(len(snapshot), 1)
        key, state = next(iter(snapshot.items()))
        self.assertEqual(state[0], 1)
        self.assertTrue(service._eligible(__import__("pathlib").Path(key), state))

        self.set("min_size", 10)
        service = WatchService(self.config, [self.inbox], lambda path: None)
        key, state = next(iter(service._snapshot().items()))
        self.assertFalse(service._eligible(__import__("pathlib").Path(key), state))

    def test_process_existing_dispatches(self):
        self.write("existing.txt", "x")
        seen: list[str] = []
        event = threading.Event()

        def on_file(path):
            seen.append(path.name)
            event.set()

        service = WatchService(
            self.config,
            [self.inbox],
            on_file,
            interval=0.25,
            stability=0.0,
            process_existing=True,
        )
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        try:
            self.assertTrue(event.wait(5), "watcher did not dispatch existing file")
        finally:
            service.stop()
            thread.join(timeout=5)
        self.assertEqual(seen, ["existing.txt"])

    def test_new_file_dispatch(self):
        seen: list[str] = []
        event = threading.Event()

        def on_file(path):
            seen.append(path.name)
            event.set()

        service = WatchService(
            self.config,
            [self.inbox],
            on_file,
            interval=0.25,
            stability=0.0,
            process_existing=False,
        )
        service.start()
        try:
            time.sleep(0.6)
            self.write("new.txt", "x")
            self.assertTrue(event.wait(6), "watcher did not dispatch new file")
        finally:
            service.stop()
            service.join(timeout=5)
        self.assertEqual(seen, ["new.txt"])

    def test_errors_do_not_stop_watcher(self):
        self.write("one.txt", "x")
        errors = []

        def on_file(path):
            raise RuntimeError("boom")

        service = WatchService(
            self.config,
            [self.inbox],
            on_file,
            interval=0.25,
            stability=0.0,
            process_existing=True,
            on_error=lambda path, exc: errors.append(str(exc)),
        )
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not errors:
                time.sleep(0.1)
        finally:
            service.stop()
            thread.join(timeout=5)
        self.assertTrue(any("boom" in error for error in errors))

    def test_start_stop_is_idempotent(self):
        service = WatchService(self.config, [self.inbox], lambda path: None, interval=0.25)
        service.start()
        service.start()
        service.stop()
        service.join(timeout=5)
        service.stop()


if __name__ == "__main__":
    unittest.main()
