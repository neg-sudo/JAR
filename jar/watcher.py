"""Dependency-free live folder watcher based on stable snapshots."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import Config
from .errors import JarError
from .rules import RuleEngine
from .scanner import iter_files
from .utils import expand_path

log = logging.getLogger("jar.watch")

FileCallback = Callable[[Path], None]
ErrorCallback = Callable[[Path, OSError], None]


class WatchService:
    """Watch folders and call ``on_file`` once a new file is stable.

    Polling is used instead of platform-specific inotify/FSEvents so the
    watcher behaves identically on Windows, macOS, Linux and network shares.
    ``stability`` seconds of unchanged size/mtime avoids moving files while
    they are still downloading.
    """

    def __init__(
        self,
        config: Config,
        paths: Iterable[str | Path] | None,
        on_file: FileCallback,
        *,
        recursive: bool | None = None,
        interval: float | None = None,
        stability: float | None = None,
        process_existing: bool = False,
        on_error: ErrorCallback | None = None,
    ):
        self.config = config
        self.engine = RuleEngine(config)
        raw_paths = list(paths) if paths else list(config.watch_dirs)
        self.paths = [path for path in (expand_path(value) for value in raw_paths) if path]
        if not self.paths:
            raise JarError("no folders to watch")
        for path in self.paths:
            if not path.exists():
                raise JarError(f"watch folder does not exist: {path}")
        self.on_file = on_file
        self.on_error = on_error
        self.recursive = bool(config.data.get("recursive") if recursive is None else recursive)
        self.interval = max(0.25, float(config.data.get("watch_interval", 2.0) if interval is None else interval))
        self.stability = max(0.0, float(config.data.get("watch_stability", 2.0) if stability is None else stability))
        self.process_existing = process_existing
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, tuple[float, int, float]] = {}
        self._known: dict[str, tuple[int, float]] = {}

    # ------------------------------------------------------------------ scans
    def _snapshot(self) -> dict[str, tuple[int, float]]:
        snapshot: dict[str, tuple[int, float]] = {}
        for path in iter_files(
            self.paths,
            recursive=self.recursive,
            follow_symlinks=bool(self.config.data.get("follow_symlinks", False)),
            ignore_dir=lambda candidate: self.engine.is_ignored_dir(candidate, self.paths),
            on_error=self.on_error,
        ):
            if self.engine.is_ignored(path, self.paths):
                continue
            if self.engine.in_destination(path):
                continue
            try:
                stat_result = path.stat()
            except OSError as exc:
                if self.on_error:
                    self.on_error(path, exc)
                continue
            if not path.is_file():
                continue
            try:
                key = str(path.resolve(strict=False))
            except OSError:
                key = str(path)
            snapshot[key] = (int(stat_result.st_size), float(stat_result.st_mtime))
        return snapshot

    def _eligible(self, path: Path, stat_result: tuple[int, float]) -> bool:
        data = self.config.data
        size, mtime = stat_result
        age = max(0.0, time.time() - mtime)
        min_age = int(data.get("min_age_seconds") or 0)
        max_age = int(data.get("max_age_seconds") or 0)
        min_size = int(data.get("min_size") or 0)
        max_size = int(data.get("max_size") or 0)
        if min_age and age < min_age:
            return False
        if max_age and age > max_age:
            return False
        if min_size and size < min_size:
            return False
        if max_size and size > max_size:
            return False
        return True

    # ------------------------------------------------------------------- loop
    def run(self) -> None:
        self._known = self._snapshot()
        if self.process_existing:
            for path_key in sorted(self._known):
                self._dispatch(Path(path_key))
        while not self._stop.is_set():
            current = self._snapshot()
            now = time.time()
            for key, state in current.items():
                if key not in self._known:
                    self._pending[key] = (now, state[0], state[1])
                    continue
                pending = self._pending.get(key)
                if pending:
                    if pending[1] != state[0] or pending[2] != state[1]:
                        self._pending[key] = (now, state[0], state[1])
            for key in list(self._pending):
                if key not in current:
                    self._pending.pop(key, None)
                    continue
                first_seen, _size, _mtime = self._pending[key]
                if now - first_seen < self.stability:
                    continue
                if not self._eligible(Path(key), current[key]):
                    continue
                self._pending.pop(key, None)
                self._dispatch(Path(key))
            self._known = current
            self._stop.wait(self.interval)

    def _dispatch(self, path: Path) -> None:
        try:
            self.on_file(path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the watcher
            log.exception("watch callback failed for %s: %s", path, exc)
            if self.on_error:
                self.on_error(path, OSError(str(exc)))

    # ------------------------------------------------------------------ thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="jar-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)
