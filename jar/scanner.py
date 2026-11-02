"""File discovery and filtering."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .config import Config
from .rules import RuleEngine, RuleMatch
from .safety import is_protected_root
from .utils import path_is_within

ErrorCallback = Callable[[Path, OSError], None]


@dataclass
class Candidate:
    path: Path
    size: int
    mtime: float
    match: RuleMatch

    def describe(self) -> dict:
        return {
            "path": str(self.path),
            "size": self.size,
            "mtime": self.mtime,
            "category": self.match.category,
            "rule": self.match.rule,
        }


def _emit_error(callback: ErrorCallback | None, path: Path, exc: OSError) -> None:
    if callback:
        callback(path, exc)


def iter_files(
    paths: Iterable[str | os.PathLike[str]],
    *,
    recursive: bool = False,
    follow_symlinks: bool = False,
    ignore_dir: Callable[[Path], bool] | None = None,
    on_error: ErrorCallback | None = None,
) -> Iterator[Path]:
    """Yield files under *paths* without third-party dependencies.

    Directory symlinks are not followed unless ``follow_symlinks`` is true, and
    hidden/ignored directories are pruned during traversal for speed.
    """
    for raw in paths:
        try:
            root = Path(raw).expanduser()
        except (OSError, ValueError):
            continue
        if root.is_file() or (root.is_symlink() and follow_symlinks):
            if not root.is_symlink() or follow_symlinks:
                yield root
            continue
        if not root.is_dir():
            continue
        if not recursive:
            try:
                entries = sorted(os.scandir(root), key=lambda entry: entry.name.lower())
            except OSError as exc:
                _emit_error(on_error, root, exc)
                continue
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                    is_file = entry.is_file(follow_symlinks=follow_symlinks)
                except OSError as exc:
                    _emit_error(on_error, Path(entry.path), exc)
                    continue
                path = Path(entry.path)
                if is_dir:
                    if ignore_dir and ignore_dir(path):
                        continue
                    continue
                if is_file:
                    if path.is_symlink() and not follow_symlinks:
                        continue
                    yield path
            continue

        for current, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=follow_symlinks, onerror=lambda exc: _emit_error(on_error, root, exc)
        ):
            current_path = Path(current)
            kept: list[str] = []
            for name in sorted(dirnames, key=str.lower):
                child = current_path / name
                if not follow_symlinks and child.is_symlink():
                    continue
                if ignore_dir and ignore_dir(child):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in sorted(filenames, key=str.lower):
                path = current_path / name
                if path.is_symlink() and not follow_symlinks:
                    continue
                yield path


def scan_candidates(
    paths: Iterable[str | os.PathLike[str]],
    config: Config,
    engine: RuleEngine | None = None,
    *,
    recursive: bool | None = None,
    categories: Iterable[str] | None = None,
    include_protected: bool = False,
    on_error: ErrorCallback | None = None,
) -> list[Candidate]:
    """Scan and filter files according to the effective configuration."""
    engine = engine or RuleEngine(config)
    data = config.data
    recursive = bool(data.get("recursive") if recursive is None else recursive)
    follow = bool(data.get("follow_symlinks", False))
    min_age = int(data.get("min_age_seconds") or 0)
    max_age = int(data.get("max_age_seconds") or 0)
    min_size = int(data.get("min_size") or 0)
    max_size = int(data.get("max_size") or 0)
    include = set(categories or data.get("include_categories") or [])
    exclude = set(data.get("exclude_categories") or [])

    roots: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not include_protected and path.is_dir() and is_protected_root(path, data.get("protected_paths")):
            raise ValueError(f"refusing to watch a protected system folder: {path}")
        roots.append(path)

    candidates: list[Candidate] = []
    seen: set[str] = set()
    now = time.time()

    for path in iter_files(
        roots,
        recursive=recursive,
        follow_symlinks=follow,
        ignore_dir=lambda candidate: engine.is_ignored_dir(candidate, roots),
        on_error=on_error,
    ):
        try:
            resolved_key = str(path.resolve(strict=False))
        except OSError:
            resolved_key = str(path)
        if resolved_key in seen:
            continue
        seen.add(resolved_key)

        if engine.is_ignored(path, roots):
            continue
        if engine.in_destination(path):
            continue

        try:
            stat_result = path.stat()
        except OSError as exc:
            _emit_error(on_error, path, exc)
            continue
        if not path.is_file():
            continue
        count_size = stat_result.st_size
        age = max(0.0, now - stat_result.st_mtime)
        if min_age and age < min_age:
            continue
        if max_age and age > max_age:
            continue
        if min_size and count_size < min_size:
            continue
        if max_size and count_size > max_size:
            continue

        try:
            match = engine.classify(path, stat_result)
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort a scan
            _emit_error(on_error, path, OSError(str(exc)))
            continue
        if include and match.category not in include:
            continue
        if exclude and match.category in exclude:
            continue
        candidates.append(Candidate(path=path, size=count_size, mtime=stat_result.st_mtime, match=match))

    candidates.sort(key=lambda item: str(item.path).lower())
    return candidates


def path_inside_any(path: Path, roots: Iterable[Path]) -> bool:
    return any(path_is_within(path, root) for root in roots)
